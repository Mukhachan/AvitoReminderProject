import asyncio
import json
import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from avito_reminder.avito import (
    AvitoBlockedError,
    AvitoClient,
    AvitoError,
    AvitoNetworkError,
    AvitoParseError,
    _AvitoProxyPool,
    _AvitoProxyRotationRequired,
    _playwright_proxy,
    build_search_url,
    city_slug,
    parse_search_html,
)
from avito_reminder.avito_mfe import (
    AvitoPageState,
    build_api_params,
    extract_page_state,
    parse_api_response,
)
from avito_reminder.models import AvitoItem

from .helpers import settings


class RouteStubClient(AvitoClient):
    def __init__(self, client_settings, proxy_error: AvitoError | None = None):
        super().__init__(client_settings)
        self.calls: list[bool] = []
        self.proxy_error = proxy_error

    async def _search_route(self, url, headers, *, use_proxy):
        self.calls.append(use_proxy)
        if not use_proxy:
            raise AvitoBlockedError("Avito вернул HTTP 429")
        if self.proxy_error:
            raise self.proxy_error
        return []


class BrowserStubClient(AvitoClient):
    async def _search_browser(self, url, **_kwargs):
        return []


class RestartingBrowserClient(AvitoClient):
    def __init__(self, client_settings):
        super().__init__(client_settings)
        self.start_calls = 0
        self.search_calls = 0

    async def _start_browser(self) -> None:
        self.start_calls += 1
        self._browser_context = SimpleNamespace()  # type: ignore[assignment]

    async def _wait_for_browser_slot(self) -> None:
        return None

    async def _search_browser_with_current_proxy(self, *_args, **_kwargs):
        self.search_calls += 1
        if self.search_calls == 1:
            raise PlaywrightError(
                "BrowserContext.new_page: Target page, context or browser has been closed"
            )
        return []


class ReloadingPageStub:
    def __init__(self, responses: list[tuple[int, str]]):
        self.responses = responses
        self.html = ""
        self.url = "https://www.avito.ru/"
        self.reload_count = 0

    async def reload(self, **_kwargs):
        status, self.html = self.responses.pop(0)
        self.reload_count += 1
        return SimpleNamespace(status=status)

    async def content(self) -> str:
        return self.html

    def is_closed(self) -> bool:
        return False


class BlankTimeoutPageStub:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.closed = False
        self.screenshot_calls = 0
        self.status_content_calls = 0

    async def set_content(self, *_args, **_kwargs) -> None:
        self.status_content_calls += 1

    async def goto(self, *_args, **_kwargs):
        raise PlaywrightTimeoutError("navigation timeout")

    async def screenshot(self, **_kwargs) -> None:
        self.screenshot_calls += 1

    async def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


class PublicIpRequestContextStub:
    def __init__(self) -> None:
        self.disposed = False
        self.requested_url: str | None = None

    async def get(self, url: str, **_kwargs):
        self.requested_url = url
        return SimpleNamespace(
            ok=True,
            status=200,
            json=self._json,
        )

    async def _json(self):
        return {"ip": "203.0.113.42"}

    async def dispose(self) -> None:
        self.disposed = True


class PublicIpRequestFactoryStub:
    def __init__(self, context: PublicIpRequestContextStub) -> None:
        self.context = context
        self.proxy = None

    async def new_context(self, *, proxy=None):
        self.proxy = proxy
        return self.context


def test_build_search_url_encodes_parameters() -> None:
    url = build_search_url("iPhone 13 128 GB", "Москва", 30_000, 50_000)
    parsed = urlparse(url)
    assert parsed.path == "/moskva"
    assert parse_qs(parsed.query) == {
        "q": ["iPhone 13 128 GB"],
        "s": ["104"],
        "pmin": ["30000"],
        "pmax": ["50000"],
    }


def test_city_slug_supports_alias_and_transliteration() -> None:
    assert city_slug("СПб") == "sankt-peterburg"
    assert city_slug("Йошкар-Ола") == "yoshkar-ola"


def test_build_search_url_rejects_inverted_price_range() -> None:
    with pytest.raises(ValueError, match="Минимальная цена"):
        build_search_url("велосипед", "Казань", 20_000, 10_000)


def test_parse_search_cards() -> None:
    html = """
    <html><body>
      <div data-marker="item" data-item-id="1234567890">
        <a data-marker="item-title" href="/moskva/telefony/iphone_13_1234567890">
          <h3>Apple iPhone 13 128 GB</h3>
        </a>
        <p data-marker="item-price"><meta itemprop="price" content="45000">45 000 ₽</p>
        <div data-marker="item-address">Москва, Арбат</div>
        <img src="https://example.test/iphone.jpg">
      </div>
    </body></html>
    """
    items = parse_search_html(html)
    assert len(items) == 1
    assert items[0].id == "1234567890"
    assert items[0].title == "Apple iPhone 13 128 GB"
    assert items[0].price == 45_000
    assert items[0].location == "Москва, Арбат"


def test_parse_json_ld_fallback() -> None:
    payload = {
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "Product",
                "name": "Фотоаппарат",
                "url": "/moskva/fototehnika/fotoapparat_9876543210",
                "offers": {"price": "12500"},
            }
        ],
    }
    html = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    items = parse_search_html(html)
    assert [(item.id, item.price) for item in items] == [("9876543210", 12_500)]


def test_parse_mfe_state_before_dom_fallback() -> None:
    payload = {
        "i18n": {"hasMessages": True},
        "loaderData": {
            "data": {
                "context": "search-context-token",
                "searchCore": {
                    "categoryId": 99,
                    "locationId": 637640,
                    "priceMin": 10_000,
                    "params": {"201": ["1059"]},
                },
                "catalog": {
                    "items": [
                        {
                            "id": 1234567890,
                            "urlPath": "/moskva/telefony/iphone_1234567890",
                            "title": "Apple iPhone",
                            "priceDetailed": {"value": 45_000},
                            "addressDetailed": {"locationName": "Москва, Арбат"},
                            "gallery": {
                                "imageLargeUrl": "https://example.test/iphone.jpg"
                            },
                        }
                    ]
                },
            }
        },
    }
    html = (
        '<script type="mime/invalid" data-mfe-state="true">'
        f"{json.dumps(payload)}"
        "</script>"
    )

    state = extract_page_state(html)
    assert state is not None
    assert state.context == "search-context-token"
    assert state.api_params == {
        "categoryId": "99",
        "locationId": "637640",
        "pmin": "10000",
        "params[201]": "1059",
    }
    assert parse_search_html(html) == list(state.items)
    assert state.items[0].location == "Москва, Арбат"
    assert state.items[0].image_url == "https://example.test/iphone.jpg"


def test_parse_internal_api_response_variants() -> None:
    item = {
        "id": "9876543210",
        "urlPath": "/kazan/velosipedy/velosiped_9876543210",
        "title": "Велосипед",
        "priceDetailed": {"value": 12_500},
        "location": {"name": "Казань"},
    }

    direct = parse_api_response({"catalog": {"items": [item]}})
    nested = parse_api_response({"result": {"catalog": {"items": [item]}}})

    assert direct == nested
    assert [(result.id, result.price) for result in direct] == [("9876543210", 12_500)]


def test_build_api_params_keeps_stable_search_context() -> None:
    assert build_api_params(
        {
            "categoryId": 1,
            "geoCoords": {"lat": 55.75, "lng": 37.62},
            "withDeliveryOnly": True,
            "searchRadius": 25,
        }
    ) == {
        "categoryId": "1",
        "geoCoords": '{"lat":55.75,"lng":37.62}',
        "cd": "1",
        "radius": "25",
    }


def test_hybrid_transport_uses_api_pages_until_result_limit(tmp_path, monkeypatch) -> None:
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            max_results=3,
            avito_api_max_pages=4,
        )
    )
    first = AvitoItem("1", "Первое", 100, "https://www.avito.ru/item_1000001")
    state = AvitoPageState((first,), "context-token", {"categoryId": "1"})
    requested_pages: list[int] = []
    synchronized: list[object] = []
    fake_session = object()

    async def fake_get_session():
        return fake_session

    async def fake_sync(session):
        synchronized.append(session)

    async def fake_request(*, page_number, **_kwargs):
        requested_pages.append(page_number)
        return [
            AvitoItem(
                str(page_number),
                f"Страница {page_number}",
                page_number * 100,
                f"https://www.avito.ru/item_{page_number}000000",
            )
        ]

    monkeypatch.setattr(client, "_get_curl_session", fake_get_session)
    monkeypatch.setattr(client, "_sync_browser_cookies_to_curl", fake_sync)
    monkeypatch.setattr(client, "_request_api_page", fake_request)

    items = asyncio.run(
        client._extend_with_api_pages(
            [first],
            page_state=state,
            search_url="https://www.avito.ru/moskva?q=test",
        )
    )

    assert [item.id for item in items] == ["1", "2", "3"]
    assert requested_pages == [2, 3]
    assert synchronized == [fake_session]


def test_parse_detects_ip_block() -> None:
    with pytest.raises(AvitoBlockedError):
        parse_search_html("<h2>Доступ ограничен: проблема с IP</h2>")


def test_parse_accepts_confirmed_empty_result() -> None:
    assert parse_search_html("<main>По вашему запросу ничего не найдено</main>") == []


def test_parse_rejects_unknown_layout() -> None:
    with pytest.raises(AvitoParseError):
        parse_search_html("<html><title>Avito</title><body>Неизвестная разметка</body></html>")


def test_avito_falls_back_from_direct_to_socks_proxy(tmp_path) -> None:
    client = RouteStubClient(
        settings(
            tmp_path / "test.db",
            http_proxy="socks5://127.0.0.1:20808",
            avito_proxy_mode="fallback",
        )
    )

    assert asyncio.run(client.search("https://www.avito.ru/moskva")) == []
    assert client.calls == [False, True]
    assert client.last_route == "proxy"


def test_avito_fallback_preserves_blocked_error(tmp_path) -> None:
    client = RouteStubClient(
        settings(
            tmp_path / "test.db",
            http_proxy="socks5://127.0.0.1:20808",
            avito_proxy_mode="fallback",
        ),
        proxy_error=AvitoNetworkError("прокси недоступен"),
    )

    with pytest.raises(AvitoBlockedError, match="direct:.*proxy:"):
        asyncio.run(client.search("https://www.avito.ru/moskva"))
    assert client.calls == [False, True]


def test_proxy_pool_starts_direct_and_rotates_sticky_endpoints(tmp_path) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    pool = _AvitoProxyPool(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="fallback",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
        )
    )

    assert pool.current is None
    assert pool.rotate() == first
    assert pool.rotate() == second
    assert pool.rotate() == first


def test_proxy_mode_starts_immediately_on_random_pool_endpoint(
    tmp_path, monkeypatch
) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    monkeypatch.setattr("avito_reminder.avito.random.randrange", lambda _size: 1)
    pool = _AvitoProxyPool(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
        )
    )

    assert pool.current == second
    assert pool.rotate() == first


def test_playwright_proxy_keeps_credentials_out_of_server_url() -> None:
    assert _playwright_proxy(
        "http://user%40account:password%3Avalue@proxy.example.test:1000"
    ) == {
        "server": "http://proxy.example.test:1000",
        "username": "user@account",
        "password": "password:value",
    }


def test_public_ip_is_logged_through_current_proxy(tmp_path, caplog) -> None:
    proxy_url = "http://user:password@proxy.example.test:1000"
    request_context = PublicIpRequestContextStub()
    request_factory = PublicIpRequestFactoryStub(request_context)
    client = AvitoClient(settings(tmp_path / "test.db"))
    client._playwright = SimpleNamespace(request=request_factory)  # type: ignore[assignment]
    caplog.set_level(logging.INFO, logger="avito_reminder.avito")

    asyncio.run(client._log_browser_public_ip(proxy_url))

    assert request_factory.proxy == {
        "server": "http://proxy.example.test:1000",
        "username": "user",
        "password": "password",
    }
    assert request_context.requested_url == "https://api.ipify.org?format=json"
    assert request_context.disposed is True
    assert "Выходной IP Chromium для Avito: 203.0.113.42" in caplog.text
    assert "password" not in caplog.text


def test_browser_transport_uses_direct_chromium_route(tmp_path) -> None:
    client = BrowserStubClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
        )
    )

    assert asyncio.run(client.search("https://www.avito.ru/moskva")) == []
    assert client.last_route == "chromium-direct"


def test_closed_browser_is_restarted_automatically(tmp_path) -> None:
    client = RestartingBrowserClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
        )
    )

    assert asyncio.run(client.search("https://www.avito.ru/moskva")) == []
    assert client.start_calls == 2
    assert client.search_calls == 2


def test_existing_avito_tab_is_reused_between_checks(tmp_path) -> None:
    page = SimpleNamespace(
        url="https://www.avito.ru/moskva?q=test",
        is_closed=lambda: False,
    )

    class ContextStub:
        pages = [page]

        async def new_page(self):
            raise AssertionError("новая вкладка не должна создаваться")

    client = AvitoClient(settings(tmp_path / "test.db", avito_transport="browser"))
    client._browser_context = ContextStub()  # type: ignore[assignment]

    assert asyncio.run(client._acquire_browser_page()) is page


def test_browser_waits_and_reloads_until_avito_access_returns(tmp_path, monkeypatch) -> None:
    blocked_html = "<h2>Доступ ограничен: проблема с IP</h2>"
    ready_html = "<html><title>Avito</title><main>Главная</main></html>"
    page = ReloadingPageStub([(429, blocked_html), (200, ready_html)])
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_page_reload_delay_seconds=90,
        )
    )
    delays: list[float] = []
    block_notifications: list[AvitoBlockedError] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "blocked.png"

    async def on_blocked(exc: AvitoBlockedError) -> None:
        block_notifications.append(exc)

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    result = asyncio.run(
        client._wait_then_reload_avito_page(
            page,  # type: ignore[arg-type]
            status=403,
            html=blocked_html,
            page_name="главная страница",
            on_blocked=on_blocked,
        )
    )

    assert result == (200, ready_html, True)
    assert page.reload_count == 2
    assert delays == [90, 90]
    assert len(block_notifications) == 1
    assert block_notifications[0].diagnostic_path == tmp_path / "blocked.png"


def test_browser_continues_without_wait_or_reload_when_page_opened_normally(
    tmp_path, monkeypatch
) -> None:
    ready_html = "<html><title>Avito</title><main>Главная</main></html>"
    page = ReloadingPageStub([])
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_page_reload_delay_seconds=90,
        )
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)

    result = asyncio.run(
        client._wait_then_reload_avito_page(
            page,  # type: ignore[arg-type]
            status=200,
            html=ready_html,
            page_name="главная страница",
        )
    )

    assert result == (200, ready_html, False)
    assert page.reload_count == 0
    assert delays == []


def test_browser_starts_global_cooldown_after_repeated_reload_errors(
    tmp_path, monkeypatch
) -> None:
    blocked_html = "<h2>Доступ ограничен: проблема с IP</h2>"
    page = ReloadingPageStub([(429, blocked_html)] * 3)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_page_reload_delay_seconds=90,
            avito_error_reload_attempts=3,
            avito_cooldown_seconds=10_800,
        )
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "blocked.png"

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    async def scenario() -> None:
        with pytest.raises(AvitoBlockedError) as caught:
            await client._wait_then_reload_avito_page(
                page,  # type: ignore[arg-type]
                status=403,
                html=blocked_html,
                page_name="главная страница",
            )
        assert caught.value.retry_after_seconds == 10_800
        with pytest.raises(AvitoBlockedError) as cooldown:
            client._raise_if_cooling_down()
        assert cooldown.value.retry_after_seconds is not None
        assert cooldown.value.retry_after_seconds > 10_700

    asyncio.run(scenario())

    assert page.reload_count == 3
    assert delays == [90, 90, 90]


def test_browser_requests_proxy_rotation_before_global_cooldown(
    tmp_path, monkeypatch
) -> None:
    blocked_html = "<h2>Доступ ограничен: проблема с IP</h2>"
    page = ReloadingPageStub([(429, blocked_html)])
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="fallback",
            avito_proxy_pool=("http://user:password@proxy.example.test:1000",),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotate_after_reloads=1,
            avito_page_reload_delay_seconds=90,
        )
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "blocked.png"

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    async def scenario() -> None:
        with pytest.raises(_AvitoProxyRotationRequired) as caught:
            await client._wait_then_reload_avito_page(
                page,  # type: ignore[arg-type]
                status=403,
                html=blocked_html,
                page_name="главная страница",
            )
        assert caught.value.retry_after_seconds is None
        assert client._cooldown_until is None

    asyncio.run(scenario())

    assert page.reload_count == 1
    assert delays == [90]


def test_proxy_rotation_recreates_network_on_next_endpoint(tmp_path, monkeypatch) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    monkeypatch.setattr("avito_reminder.avito.random.randrange", lambda _size: 0)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotation_delay_seconds=0,
        )
    )
    events: list[str] = []

    async def fake_close_network() -> None:
        events.append("closed")

    async def fake_change_url() -> None:
        events.append("change-url")

    monkeypatch.setattr(client, "_close_browser_network", fake_close_network)
    monkeypatch.setattr(client, "_call_proxy_change_url", fake_change_url)

    asyncio.run(client._rotate_avito_proxy(1))

    assert events == ["closed", "change-url"]
    assert client._avito_proxies.current == second
    assert client.last_route == "chromium+curl-proxy"


def test_proxy_timeout_on_about_blank_rotates_without_screenshot(tmp_path) -> None:
    page = BlankTimeoutPageStub()
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="proxy",
            avito_proxy_pool=("http://user:password@proxy.example.test:1000",),
            avito_proxy_rotation_enabled=True,
            avito_browser_headless=False,
        )
    )
    client._browser_context = SimpleNamespace(pages=[page])  # type: ignore[assignment]

    with pytest.raises(_AvitoProxyRotationRequired, match="about:blank"):
        asyncio.run(
            client._search_browser_with_current_proxy(
                "https://www.avito.ru/moskva?q=test"
            )
        )

    assert page.closed is False
    assert page.screenshot_calls == 0
    assert page.status_content_calls == 1
