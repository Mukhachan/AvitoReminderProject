import asyncio
import json
import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from curl_cffi.requests import AsyncSession as CurlAsyncSession
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from avito_reminder.avito import (
    AvitoBlockedError,
    AvitoCaptchaRequiredError,
    AvitoClient,
    AvitoError,
    AvitoHardBlockedError,
    AvitoNetworkError,
    AvitoParseError,
    AvitoRateLimitedError,
    AvitoSessionError,
    _AvitoProxyPool,
    _AvitoProxyRotationRequired,
    _has_target_search_query,
    _looks_like_loaded_avito_home_html,
    _playwright_proxy,
    _proxy_route_id,
    _retry_after_seconds,
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
from avito_reminder.browser_identity import load_browser_identity
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


class DelayedHomePageStub(ReloadingPageStub):
    def __init__(self, blocked_html: str, ready_html: str):
        super().__init__([(200, blocked_html)])
        self.html = blocked_html
        self.ready_html = ready_html
        self.home_ready = False
        self.wait_for_home_count = 0
        self.url = "https://www.avito.ru/#block"

    async def evaluate(self, _script: str) -> bool:
        return self.home_ready

    async def wait_for_function(self, _script: str, **_kwargs) -> None:
        self.wait_for_home_count += 1
        if self.reload_count == 0:
            return
        self.home_ready = True
        self.html = self.ready_html


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


class CookieBrowserContextStub:
    def __init__(self) -> None:
        self.added_cookies: list[dict[str, object]] = []

    async def cookies(self, _urls):
        return [
            {
                "name": "ft",
                "value": "browser-token",
                "domain": ".avito.ru",
                "path": "/",
                "secure": True,
                "expires": 2_000_000_000,
            },
            {
                "name": "expired",
                "value": "old",
                "domain": ".avito.ru",
                "path": "/",
                "secure": True,
                "expires": 1,
            },
        ]

    async def add_cookies(self, cookies):
        self.added_cookies.extend(cookies)


class CurlApiResponseStub:
    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        headers: dict[str, str] | None = None,
        payload: object | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload

    def json(self) -> object:
        return self._payload


class CurlApiSessionStub:
    def __init__(self, response: CurlApiResponseStub) -> None:
        self.response = response

    async def get(self, *_args, **_kwargs) -> CurlApiResponseStub:
        return self.response


class BrowserLaunchContextStub:
    def __init__(self) -> None:
        self.init_scripts: list[str] = []
        self.extra_http_headers: dict[str, str] = {}
        self.close_callback = None
        self.saved_storage_paths: list[str] = []
        self.saved_indexed_db: list[bool | None] = []

    async def add_init_script(self, *, script: str) -> None:
        self.init_scripts.append(script)

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        self.extra_http_headers = headers

    def on(self, event: str, callback) -> None:
        assert event == "close"
        self.close_callback = callback

    async def new_page(self):
        return SimpleNamespace()

    async def storage_state(self, *, path: str, indexed_db: bool | None = None):
        self.saved_storage_paths.append(path)
        self.saved_indexed_db.append(indexed_db)


class BrowserLaunchStub:
    def __init__(self, context: BrowserLaunchContextStub) -> None:
        self.context = context
        self.context_options = None
        self.disconnect_callback = None

    async def new_context(self, **options):
        self.context_options = options
        return self.context

    def on(self, event: str, callback) -> None:
        assert event == "disconnected"
        self.disconnect_callback = callback


class ChromiumLauncherStub:
    def __init__(self, context: BrowserLaunchContextStub) -> None:
        self.browser = BrowserLaunchStub(context)
        self.options = None

    async def launch(self, **options):
        self.options = options
        return self.browser


class IdentityPageStub:
    url = "https://www.avito.ru/#block"

    def __init__(self) -> None:
        self.evaluated_scripts: list[str] = []

    def is_closed(self) -> bool:
        return False

    async def evaluate(self, script: str) -> None:
        self.evaluated_scripts.append(script)


class BlockedIdentityContextStub:
    def __init__(self) -> None:
        self.page = IdentityPageStub()
        self.pages = [self.page]
        self.cookies_cleared = False
        self.closed = False

    async def clear_cookies(self) -> None:
        self.cookies_cleared = True

    async def close(self) -> None:
        self.closed = True


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


def test_target_search_url_checks_path_filters_and_block_fragment() -> None:
    target = "https://www.avito.ru/moskva?q=iphone&s=104&pmin=10000"

    assert _has_target_search_query(target, target)
    assert _has_target_search_query(
        "https://www.avito.ru/moskva/telefony?q=iphone&pmin=10000",
        target,
    )
    assert not _has_target_search_query(
        "https://www.avito.ru/moskva/telefony/apple?q=iphone&pmin=10000",
        target,
    )
    assert not _has_target_search_query(
        "https://www.avito.ru/kazan?q=iphone&s=104&pmin=10000",
        target,
    )
    assert not _has_target_search_query(
        "https://www.avito.ru/moskva?q=iphone&s=104&pmin=20000",
        target,
    )
    assert not _has_target_search_query(f"{target}#block", target)


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


@pytest.mark.parametrize(
    "pagination_error",
    [
        AvitoBlockedError("blocked"),
        AvitoRateLimitedError("rate limited", retry_after_seconds=900),
        AvitoSessionError("session rejected", retry_after_seconds=900),
    ],
)
def test_optional_api_page_failure_keeps_successful_first_page(
    tmp_path, monkeypatch, pagination_error
) -> None:
    first = AvitoItem("1", "Первое", 100, "https://www.avito.ru/item_1000001")
    state = AvitoPageState((first,), "context-token", {"categoryId": "1"})
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            max_results=10,
            avito_api_max_pages=3,
        )
    )

    async def fake_get_session():
        return object()

    async def fake_sync(_session):
        return None

    async def fake_request(**_kwargs):
        raise pagination_error

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

    assert items == [first]
    assert client._route_health.quarantine_remaining(client._route_health_key()) == 0
    assert (
        client._route_health.quarantine_remaining(
            f"optional-api:{client._route_health_key()}"
        )
        > 0
    )


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (CurlApiResponseStub(429, headers={"Retry-After": "75"}), AvitoRateLimitedError),
        (
            CurlApiResponseStub(403, text="<h2>Блокировка IP</h2>"),
            AvitoBlockedError,
        ),
    ],
)
def test_optional_api_rejection_does_not_poison_browser_or_route(
    tmp_path,
    monkeypatch,
    response,
    error_type,
) -> None:
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            request_retries=1,
            avito_min_request_interval_seconds=1,
            avito_request_jitter_seconds=0,
        )
    )
    session = CurlApiSessionStub(response)
    cookie_syncs: list[object] = []

    async def fake_get_session():
        return session

    async def fake_before_request():
        return None

    async def fake_sync(current_session):
        cookie_syncs.append(current_session)

    monkeypatch.setattr(client, "_get_curl_session", fake_get_session)
    monkeypatch.setattr(client, "_before_avito_request", fake_before_request)
    monkeypatch.setattr(client, "_sync_curl_cookies_to_browser", fake_sync)
    state = AvitoPageState((), "context-token", {"categoryId": "1"})

    with pytest.raises(error_type):
        asyncio.run(
            client._request_api_page(
                page_number=2,
                page_state=state,
                search_url="https://www.avito.ru/moskva?q=test",
            )
        )

    assert cookie_syncs == []
    assert client._route_health.quarantine_remaining(client._route_health_key()) == 0


def test_parse_detects_ip_block() -> None:
    with pytest.raises(AvitoBlockedError):
        parse_search_html("<h2>Доступ ограничен: проблема с IP</h2>")


def test_parse_accepts_results_with_hidden_stale_block_marker() -> None:
    html = """
      <div hidden>Доступ ограничен: проблема с IP</div>
      <main data-marker="catalog-serp">
        <div data-marker="item" data-item-id="1234567890">
          <a data-marker="item-title" href="/moskva/item_1234567890">
            <h3>Рабочая карточка</h3>
          </a>
        </div>
      </main>
    """

    assert [item.id for item in parse_search_html(html)] == ["1234567890"]


def test_parse_accepts_confirmed_empty_result() -> None:
    assert parse_search_html("<main>По вашему запросу ничего не найдено</main>") == []


def test_parse_rejects_nonempty_catalog_when_no_items_match_known_schema() -> None:
    payload = {
        "loaderData": {
            "data": {"catalog": {"items": [{"unexpected": "new-schema"}]}}
        }
    }
    html = f'<script data-mfe-state="true">{json.dumps(payload)}</script>'

    with pytest.raises(AvitoParseError, match="catalog"):
        parse_search_html(html)


def test_parse_does_not_treat_unhydrated_empty_mfe_catalog_as_empty_result() -> None:
    payload = {"loaderData": {"data": {"catalog": {"items": []}}}}
    html = f'<script data-mfe-state="true">{json.dumps(payload)}</script>'

    with pytest.raises(AvitoParseError):
        parse_search_html(html)


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


def test_single_static_proxy_does_not_claim_rotation_is_available(tmp_path) -> None:
    proxy = "http://user:password@proxy.example.test:1000"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(proxy,),
            avito_proxy_rotation_enabled=True,
        )
    )

    assert client._proxy_rotation_available() is False


def test_fallback_can_rotate_from_direct_to_one_static_proxy(tmp_path) -> None:
    proxy = "http://user:password@proxy.example.test:1000"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="fallback",
            avito_proxy_pool=(proxy,),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotation_delay_seconds=0,
        )
    )

    assert client._avito_proxies.current is None
    assert client._proxy_rotation_available() is True

    asyncio.run(client._rotate_avito_proxy(1))

    assert client._avito_proxies.current == proxy


def test_proxy_start_skips_a_persistently_quarantined_route(tmp_path) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
        )
    )
    current = client._avito_proxies.current
    assert current in {first, second}
    client._route_health.quarantine(
        client._route_health_key(),
        3600,
        "test",
    )

    asyncio.run(client._prepare_browser_start())

    assert client._avito_proxies.current != current


def test_fallback_start_skips_persistently_quarantined_direct_route(tmp_path) -> None:
    proxy = "http://user:password@proxy.example.test:1000"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="fallback",
            avito_proxy_pool=(proxy,),
            avito_proxy_rotation_enabled=True,
        )
    )
    client._route_health.quarantine(
        client._route_health_key(None, use_current_route=False),
        3600,
        "test",
    )

    asyncio.run(client._prepare_browser_start())

    assert client._avito_proxies.current == proxy


def test_fallback_restart_uses_persisted_public_ip_quarantine(tmp_path) -> None:
    proxy = "http://user:password@proxy.example.test:1000"
    cfg = settings(
        tmp_path / "test.db",
        avito_proxy_mode="fallback",
        avito_proxy_pool=(proxy,),
        avito_proxy_rotation_enabled=True,
    )
    first = AvitoClient(cfg)
    direct_route_id = _proxy_route_id(None)
    first._route_health.associate_public_ip(direct_route_id, "203.0.113.10")
    first._route_health.quarantine(
        first._route_health_key(None, use_current_route=False),
        3600,
        "test",
    )

    restarted = AvitoClient(cfg)
    asyncio.run(restarted._prepare_browser_start())

    assert restarted._route_health_key(None, use_current_route=False) == "ip:203.0.113.10"
    assert restarted._avito_proxies.current == proxy


def test_proxy_start_uses_shortest_quarantine_when_all_routes_are_blocked(
    tmp_path,
    monkeypatch,
) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    monkeypatch.setattr("avito_reminder.avito.random.randrange", lambda _size: 0)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
        )
    )
    client._route_health.quarantine(
        client._route_health_key(first, use_current_route=False),
        21_600,
        "test-long",
    )
    client._route_health.quarantine(
        client._route_health_key(second, use_current_route=False),
        600,
        "test-short",
    )

    with pytest.raises(AvitoRateLimitedError) as caught:
        asyncio.run(client._prepare_browser_start())

    assert caught.value.retry_after_seconds is not None
    assert 590 <= caught.value.retry_after_seconds <= 600


def test_runtime_proxy_rotation_skips_quarantined_endpoint(tmp_path, monkeypatch) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    third = "http://user:password@third.proxy.test:1000"
    monkeypatch.setattr("avito_reminder.avito.random.randrange", lambda _size: 0)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second, third),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotation_delay_seconds=0,
        )
    )
    client._route_health.quarantine(
        client._route_health_key(second, use_current_route=False),
        3600,
        "test",
    )

    asyncio.run(client._rotate_avito_proxy(1))

    assert client._avito_proxies.current == third


def test_browser_skips_endpoint_that_resolves_to_quarantined_public_ip(
    tmp_path,
    monkeypatch,
) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    monkeypatch.setattr("avito_reminder.avito.random.randrange", lambda _size: 0)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
            avito_proxy_max_rotations=1,
            avito_proxy_rotation_delay_seconds=0,
        )
    )
    client._route_health.quarantine("ip:203.0.113.10", 3600, "test")
    started_routes: list[str | None] = []

    async def fake_start_browser() -> None:
        current = client._avito_proxies.current
        started_routes.append(current)
        route_id = _proxy_route_id(current)
        public_ip = "203.0.113.10" if current == first else "203.0.113.11"
        client._route_public_ips[route_id] = public_ip
        client._route_health.associate_public_ip(route_id, public_ip)

    async def fake_start_session() -> None:
        return None

    async def fake_search(*_args, **_kwargs):
        assert client._avito_proxies.current == second
        return []

    monkeypatch.setattr(client, "_start_browser", fake_start_browser)
    monkeypatch.setattr(client, "_start_browser_session", fake_start_session)
    monkeypatch.setattr(client, "_search_browser_with_current_proxy", fake_search)

    result = asyncio.run(client._search_browser("https://www.avito.ru/moskva?q=test"))

    assert result == []
    assert started_routes == [first, second]
    assert client._avito_proxies.current == second


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


def test_browser_launch_uses_one_coherent_identity(tmp_path, monkeypatch) -> None:
    context = BrowserLaunchContextStub()
    launcher = ChromiumLauncherStub(context)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_log_public_ip=False,
            avito_browser_stealth=True,
        )
    )
    client._playwright = SimpleNamespace(chromium=launcher)  # type: ignore[assignment]
    monkeypatch.setattr("avito_reminder.avito.resolve_chromium_executable", lambda _settings: None)

    asyncio.run(client._start_browser())
    asyncio.run(client._start_browser_session())

    identity = client._ensure_browser_identity()
    context_options = launcher.browser.context_options
    assert context_options["user_agent"] == identity.user_agent
    assert context_options["locale"] == identity.locale
    assert context_options["timezone_id"] == identity.timezone_id
    assert context_options["viewport"] == identity.viewport
    assert context_options["screen"] == identity.screen
    assert context.extra_http_headers == identity.http_headers
    assert "--disable-blink-features=AutomationControlled" in launcher.options["args"]
    assert context.init_scripts
    assert "Navigator.prototype, 'webdriver'" in context.init_scripts[0]


def test_browser_session_restores_storage_only_for_same_route_and_identity(
    tmp_path, monkeypatch
) -> None:
    context = BrowserLaunchContextStub()
    launcher = ChromiumLauncherStub(context)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_browser_stealth=False,
            avito_new_user_per_session=False,
            avito_log_public_ip=False,
        )
    )
    client._playwright = SimpleNamespace(chromium=launcher)  # type: ignore[assignment]
    monkeypatch.setattr("avito_reminder.avito.resolve_chromium_executable", lambda _settings: None)
    expected = client._browser_storage_state_path()
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

    asyncio.run(client._start_browser())
    asyncio.run(client._start_browser_session())

    assert launcher.browser.context_options["storage_state"] == str(expected)
    assert "user_agent" not in launcher.browser.context_options
    assert context.extra_http_headers == {}
    assert context.init_scripts == []


def test_browser_session_discards_invalid_saved_storage_and_recovers(
    tmp_path, monkeypatch
) -> None:
    context = BrowserLaunchContextStub()
    launcher = ChromiumLauncherStub(context)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_browser_stealth=False,
            avito_new_user_per_session=False,
            avito_log_public_ip=False,
        )
    )
    client._playwright = SimpleNamespace(chromium=launcher)  # type: ignore[assignment]
    monkeypatch.setattr("avito_reminder.avito.resolve_chromium_executable", lambda _settings: None)
    stored_state = client._browser_storage_state_path()
    stored_state.parent.mkdir(parents=True, exist_ok=True)
    stored_state.write_text("{truncated", encoding="utf-8")

    original_new_context = launcher.browser.new_context
    context_options: list[dict[str, object]] = []

    async def reject_stored_state_once(**options):
        context_options.append(options)
        if "storage_state" in options:
            raise PlaywrightError("invalid storage state")
        return await original_new_context(**options)

    monkeypatch.setattr(launcher.browser, "new_context", reject_stored_state_once)

    asyncio.run(client._start_browser())
    asyncio.run(client._start_browser_session())

    assert len(context_options) == 2
    assert context_options[0]["storage_state"] == str(stored_state)
    assert "storage_state" not in context_options[1]
    assert not stored_state.exists()
    assert client._browser_context is context


def test_browser_session_preserves_saved_storage_when_clean_context_also_fails(
    tmp_path, monkeypatch
) -> None:
    context = BrowserLaunchContextStub()
    launcher = ChromiumLauncherStub(context)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_browser_stealth=False,
            avito_new_user_per_session=False,
            avito_log_public_ip=False,
        )
    )
    client._playwright = SimpleNamespace(chromium=launcher)  # type: ignore[assignment]
    monkeypatch.setattr("avito_reminder.avito.resolve_chromium_executable", lambda _settings: None)
    stored_state = client._browser_storage_state_path()
    stored_state.parent.mkdir(parents=True, exist_ok=True)
    stored_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

    async def reject_every_context(**_options):
        raise PlaywrightError("browser unavailable")

    monkeypatch.setattr(launcher.browser, "new_context", reject_every_context)

    asyncio.run(client._start_browser())
    with pytest.raises(PlaywrightError, match="browser unavailable"):
        asyncio.run(client._start_browser_session())

    assert stored_state.is_file()


def test_browser_storage_state_includes_indexed_db(tmp_path) -> None:
    context = BrowserLaunchContextStub()
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_new_user_per_session=False,
        )
    )
    client._browser_context = context  # type: ignore[assignment]

    asyncio.run(client._save_browser_storage_state())

    assert context.saved_indexed_db == [True]


def test_block_rotation_discards_saved_storage_state(tmp_path) -> None:
    client = AvitoClient(settings(tmp_path / "test.db", avito_transport="browser"))
    previous = client._ensure_browser_identity()
    storage_state = client._browser_storage_state_path(identity_id=previous.identity_id)
    storage_state.parent.mkdir(parents=True, exist_ok=True)
    storage_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

    asyncio.run(client._replace_blocked_browser_identity("test block"))

    assert not storage_state.exists()
    assert client._ensure_browser_identity().identity_id != previous.identity_id


def test_next_browser_session_gets_new_process_identity_and_proxy(
    tmp_path, monkeypatch
) -> None:
    first_proxy = "http://user:password@first.proxy.test:1000"
    second_proxy = "http://user:password@second.proxy.test:1000"
    context = BrowserLaunchContextStub()
    launcher = ChromiumLauncherStub(context)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first_proxy, second_proxy),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotation_delay_seconds=0,
            avito_log_public_ip=False,
        )
    )
    client._playwright = SimpleNamespace(chromium=launcher)  # type: ignore[assignment]
    monkeypatch.setattr("avito_reminder.avito.resolve_chromium_executable", lambda _settings: None)

    asyncio.run(client._start_browser())
    first_identity = client._ensure_browser_identity()
    first_route = client._avito_proxies.current
    client._browser_sessions_started = 1
    network_closes = 0

    async def fake_close_browser_network() -> None:
        nonlocal network_closes
        network_closes += 1
        client._browser = None

    monkeypatch.setattr(client, "_close_browser_network", fake_close_browser_network)

    asyncio.run(client._prepare_new_user_session())
    asyncio.run(client._start_browser())
    second_identity = client._ensure_browser_identity()
    second_route = client._avito_proxies.current

    assert network_closes == 1
    assert second_identity.identity_id != first_identity.identity_id
    assert (second_identity.viewport_width, second_identity.viewport_height) != (
        first_identity.viewport_width,
        first_identity.viewport_height,
    )
    assert second_route != first_route


@pytest.mark.parametrize(
    ("start_with_proxy", "expected_proxy"),
    [
        (False, "http://only.proxy.test:1000"),
        (True, None),
    ],
)
def test_rotate_on_browser_start_switches_between_fallback_routes(
    tmp_path, start_with_proxy: bool, expected_proxy: str | None
) -> None:
    proxy = "http://only.proxy.test:1000"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_proxy_mode="fallback",
            avito_proxy_pool=(proxy,),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotate_on_browser_start=True,
            avito_proxy_rotation_delay_seconds=0,
            avito_identity_rotate_on_browser_start=False,
            avito_log_public_ip=False,
        )
    )
    if start_with_proxy:
        assert client._avito_proxies.rotate() == proxy
    client._browser_launches = 1

    asyncio.run(client._prepare_browser_start())

    assert client._avito_proxies.current == expected_proxy


def test_new_user_session_rotation_can_be_disabled(tmp_path, monkeypatch) -> None:
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_new_user_per_session=False,
        )
    )
    client._browser_sessions_started = 1

    async def unexpected_close() -> None:
        raise AssertionError("браузер не должен перезапускаться")

    monkeypatch.setattr(client, "_close_browser_network", unexpected_close)

    asyncio.run(client._prepare_new_user_session())


def test_client_restores_saved_identity_json(tmp_path) -> None:
    client_settings = settings(tmp_path / "test.db", avito_transport="browser")
    saved = load_browser_identity(
        profile_path=client_settings.avito_browser_profile_path,
        user_agent=client_settings.user_agent,
        impersonate="chrome",
        locale=client_settings.avito_browser_locale,
        timezone_id=client_settings.avito_browser_timezone,
    )

    current = AvitoClient(client_settings)._ensure_browser_identity()

    assert current == saved


@pytest.mark.filterwarnings("ignore::curl_cffi.utils.CurlCffiWarning")
def test_real_curl_cookie_jar_syncs_with_browser_in_both_directions(tmp_path) -> None:
    client = AvitoClient(settings(tmp_path / "test.db", avito_transport="hybrid"))
    browser_context = CookieBrowserContextStub()
    client._browser_context = browser_context  # type: ignore[assignment]

    async def scenario() -> None:
        session = CurlAsyncSession(impersonate="chrome", trust_env=False)
        try:
            await client._sync_browser_cookies_to_curl(session)
            curl_values = {cookie.name: cookie.value for cookie in session.cookies.jar}
            assert curl_values == {"ft": "browser-token"}

            session.cookies.set(
                "server-refresh",
                "new-token",
                domain=".avito.ru",
                path="/",
                secure=True,
            )
            await client._sync_curl_cookies_to_browser(session)
        finally:
            await session.close()

    asyncio.run(scenario())

    added = {cookie["name"]: cookie["value"] for cookie in browser_context.added_cookies}
    assert added == {"ft": "browser-token", "server-refresh": "new-token"}


def test_blocked_identity_clears_site_data_and_rotates_fingerprint(tmp_path) -> None:
    client = AvitoClient(settings(tmp_path / "test.db", avito_transport="hybrid"))
    context = BlockedIdentityContextStub()
    client._browser_context = context  # type: ignore[assignment]
    previous = client._ensure_browser_identity()

    asyncio.run(client._replace_blocked_browser_identity("test block"))

    current = client._ensure_browser_identity()
    assert context.cookies_cleared is True
    assert context.page.evaluated_scripts
    assert context.closed is True
    assert current.identity_id != previous.identity_id
    assert (current.viewport_width, current.viewport_height) != (
        previous.viewport_width,
        previous.viewport_height,
    )
    assert client._browser_context is None


def test_browser_transport_uses_direct_chromium_route(tmp_path) -> None:
    client = BrowserStubClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
        )
    )

    assert asyncio.run(client.search("https://www.avito.ru/moskva")) == []
    assert client.last_route == "chromium-direct"


def test_retry_after_supports_seconds_and_invalid_values() -> None:
    assert _retry_after_seconds({"Retry-After": "120"}) == 120
    assert _retry_after_seconds({"retry-after": "invalid"}) is None


def test_rate_limit_uses_retry_after_and_quarantines_route(tmp_path) -> None:
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_rate_limit_cooldown_seconds=3600,
        )
    )

    error = client._rate_limit_error({"Retry-After": "75"})

    assert isinstance(error, AvitoRateLimitedError)
    assert error.retry_after_seconds == 75
    assert client._route_health.quarantine_remaining(client._route_health_key()) > 0


def test_plain_403_is_session_error_not_ip_block(tmp_path, monkeypatch) -> None:
    page = ReloadingPageStub([])
    client = AvitoClient(settings(tmp_path / "test.db"))

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "plain-403.png"

    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    with pytest.raises(AvitoSessionError) as caught:
        asyncio.run(
            client._wait_then_reload_avito_page(
                page,  # type: ignore[arg-type]
                status=403,
                html="<html><h1>Forbidden</h1></html>",
                page_name="страница поиска",
            )
        )

    assert caught.value.retry_after_seconds == 900
    assert client._route_health.quarantine_remaining(client._route_health_key()) == 0


def test_route_health_budget_waits_after_configured_request_count(
    tmp_path, monkeypatch
) -> None:
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_min_request_interval_seconds=1,
            avito_request_window_seconds=900,
            avito_max_requests_per_window=1,
        )
    )
    client._route_health.record_request(client._route_health_key())
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)

    asyncio.run(client._before_avito_request())

    assert delays and delays[0] > 0


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


def test_captcha_page_restarts_without_waiting(tmp_path, monkeypatch) -> None:
    captcha_html = "<button>Нажмите для подтверждения</button>"
    page = ReloadingPageStub([])
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(
                "http://user:password@proxy.example.test:1000",
                "http://user:password@proxy2.example.test:1000",
            ),
            avito_proxy_rotation_enabled=True,
            avito_page_reload_delay_seconds=90,
        )
    )
    notifications: list[AvitoBlockedError] = []
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "captcha.png"

    async def on_blocked(exc: AvitoBlockedError) -> None:
        notifications.append(exc)

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    async def scenario() -> None:
        with pytest.raises(_AvitoProxyRotationRequired) as caught:
            await client._wait_then_reload_avito_page(
                page,  # type: ignore[arg-type]
                status=200,
                html=captcha_html,
                page_name="главная страница",
                on_blocked=on_blocked,
            )
        assert isinstance(caught.value.notification_error, AvitoCaptchaRequiredError)

    asyncio.run(scenario())

    assert page.reload_count == 0
    assert delays == []
    assert notifications == []


def test_hard_block_without_ip_rotation_replaces_session_and_starts_cooldown(
    tmp_path,
    monkeypatch,
) -> None:
    page = ReloadingPageStub([])
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_proxy_mode="direct",
            avito_proxy_pool=(),
            avito_proxy_rotation_enabled=False,
            avito_cooldown_seconds=7200,
        )
    )
    replacements: list[str] = []

    async def fake_replace(reason: str) -> None:
        replacements.append(reason)

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "blocked.png"

    monkeypatch.setattr(client, "_replace_blocked_browser_identity", fake_replace)
    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    with pytest.raises(AvitoBlockedError) as caught:
        asyncio.run(
            client._wait_then_reload_avito_page(
                page,  # type: ignore[arg-type]
                status=429,
                html="<h2>Блокировка IP</h2>",
                page_name="главная страница",
            )
        )

    assert replacements == ["жёсткая блокировка без доступной смены IP"]
    assert caught.value.retry_after_seconds == 7200
    assert client._cooldown_until is not None


def test_transient_ip_problem_waits_once_before_proxy_rotation(
    tmp_path, monkeypatch
) -> None:
    blocked_html = """
      <h2>Доступ ограничен: проблема с IP</h2>
      <p>Продолжить для решения капчи</p>
      <button>Продолжить</button>
    """
    page = ReloadingPageStub([(200, blocked_html)])
    page.url = "https://www.avito.ru/#block"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(
                "http://user:password@proxy.example.test:1000",
                "http://user:password@proxy2.example.test:1000",
            ),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotate_after_reloads=1,
            avito_page_reload_delay_seconds=90,
            avito_page_reload_jitter_seconds=30,
        )
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "blocked.png"

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("avito_reminder.avito.random.uniform", lambda _low, high: high)
    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    async def scenario() -> None:
        with pytest.raises(_AvitoProxyRotationRequired):
            await client._wait_then_reload_avito_page(
                page,  # type: ignore[arg-type]
                status=200,
                html=blocked_html,
                page_name="главная страница",
            )

    asyncio.run(scenario())

    assert page.reload_count == 1
    assert delays == [120]


def test_loaded_home_is_recognized_despite_stale_block_marker() -> None:
    html = """
        <html><body>
          <div hidden>Доступ ограничен: проблема с IP</div>
          <a data-marker="header/logo">Avito</a>
          <input data-marker="search-form/suggest/input"
                 placeholder="Поиск по объявлениям">
          <button data-marker="search-form/submit-button">Найти</button>
          <a>Авто</a><a>Недвижимость</a><a>Услуги</a>
          <a>Электроника</a><a>Работа</a>
        </body></html>
    """

    assert _looks_like_loaded_avito_home_html(html) is True


def test_loaded_home_with_block_fragment_does_not_wait_or_rotate(
    tmp_path, monkeypatch
) -> None:
    html = """
        <html><body>
          <div hidden>Доступ ограничен: проблема с IP</div>
          <input placeholder="Поиск по объявлениям">
          <button>Найти</button>
          <a>Авто</a><a>Недвижимость</a><a>Услуги</a><a>Электроника</a>
        </body></html>
    """
    page = ReloadingPageStub([])
    page.url = "https://www.avito.ru/#block"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(
                "http://user:password@proxy.example.test:1000",
                "http://user:password@proxy2.example.test:1000",
            ),
            avito_proxy_rotation_enabled=True,
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
            html=html,
            page_name="главная страница",
        )
    )

    assert result == (200, html, False)
    assert page.reload_count == 0
    assert delays == []


def test_parser_waits_for_home_to_finish_rendering_after_ip_problem(
    tmp_path, monkeypatch
) -> None:
    blocked_html = "<h2>Доступ ограничен: проблема с IP</h2>"
    ready_html = """
        <input placeholder="Поиск по объявлениям">
        <button>Найти</button>
        <a>Авто</a><a>Недвижимость</a><a>Услуги</a><a>Работа</a>
    """
    page = DelayedHomePageStub(blocked_html, ready_html)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_page_reload_delay_seconds=90,
            avito_error_reload_attempts=1,
        )
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_diagnostic(*_args, **_kwargs):
        return tmp_path / "blocked.png"

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    result = asyncio.run(
        client._wait_then_reload_avito_page(
            page,  # type: ignore[arg-type]
            status=200,
            html=blocked_html,
            page_name="главная страница",
        )
    )

    assert result == (200, ready_html, True)
    assert page.reload_count == 1
    assert page.wait_for_home_count == 2
    assert delays == [90]


def test_block_page_is_not_mistaken_for_loaded_home() -> None:
    html = """
        <html><body>
          <a data-marker="header/logo">Avito</a>
          <h2>Доступ ограничен: проблема с IP</h2>
        </body></html>
    """

    assert _looks_like_loaded_avito_home_html(html) is False


def test_browser_continues_without_wait_or_reload_when_page_opened_normally(
    tmp_path, monkeypatch
) -> None:
    ready_html = """
        <input placeholder="Поиск по объявлениям">
        <button>Найти</button>
        <a>Авто</a><a>Недвижимость</a><a>Услуги</a><a>Работа</a>
    """
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


def test_hard_ip_block_requests_proxy_rotation_without_waiting(tmp_path, monkeypatch) -> None:
    blocked_html = "<h2>Блокировка IP</h2>"
    page = ReloadingPageStub([])
    page.url = "https://www.avito.ru/#block"
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="fallback",
            avito_proxy_pool=(
                "http://user:password@proxy.example.test:1000",
                "http://user:password@proxy2.example.test:1000",
            ),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotate_after_reloads=1,
            avito_page_reload_delay_seconds=90,
            avito_page_reload_jitter_seconds=30,
        )
    )
    delays: list[float] = []
    notifications: list[AvitoBlockedError] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def on_blocked(exc: AvitoBlockedError) -> None:
        notifications.append(exc)

    monkeypatch.setattr("avito_reminder.avito.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("avito_reminder.avito.random.uniform", lambda _low, high: high)

    async def fake_diagnostic(_page, _status):
        return tmp_path / "blocked.png"

    monkeypatch.setattr(client, "_save_browser_diagnostic", fake_diagnostic)

    async def scenario() -> None:
        with pytest.raises(_AvitoProxyRotationRequired) as caught:
            await client._wait_then_reload_avito_page(
                page,  # type: ignore[arg-type]
                status=200,
                html=blocked_html,
                page_name="главная страница",
                on_blocked=on_blocked,
            )
        assert caught.value.retry_after_seconds is None
        assert isinstance(caught.value.notification_error, AvitoHardBlockedError)
        assert client._cooldown_until is None

    asyncio.run(scenario())

    assert page.reload_count == 0
    assert delays == []
    assert notifications == []


def test_immediate_block_rotates_before_running_notification_callback(
    tmp_path,
    monkeypatch,
) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    monkeypatch.setattr("avito_reminder.avito.random.randrange", lambda _size: 0)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
            avito_proxy_max_rotations=1,
        )
    )
    events: list[str] = []
    attempts = 0

    async def fake_start_browser() -> None:
        return None

    async def fake_start_session() -> None:
        return None

    async def fake_search(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _AvitoProxyRotationRequired(
                "blocked",
                notification_error=AvitoCaptchaRequiredError("captcha"),
            )
        return []

    async def fake_rotate(_number: int, *, replace_identity: bool = True) -> None:
        assert replace_identity is True
        events.append("rotated")

    async def on_blocked(_exc: AvitoBlockedError) -> None:
        events.append("notification-started")
        await asyncio.sleep(0)
        events.append("notification-finished")

    monkeypatch.setattr(client, "_start_browser", fake_start_browser)
    monkeypatch.setattr(client, "_start_browser_session", fake_start_session)
    monkeypatch.setattr(client, "_search_browser_with_current_proxy", fake_search)
    monkeypatch.setattr(client, "_rotate_avito_proxy", fake_rotate)

    result = asyncio.run(
        client._search_browser(
            "https://www.avito.ru/moskva?q=test",
            on_blocked=on_blocked,
        )
    )

    assert result == []
    assert events == ["rotated", "notification-started", "notification-finished"]


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
    assert client._last_avito_request_at is None


def test_exhausted_proxy_network_failure_uses_next_route_without_new_identity(
    tmp_path, monkeypatch
) -> None:
    first = "http://user:password@first.proxy.test:1000"
    second = "http://user:password@second.proxy.test:1000"
    monkeypatch.setattr("avito_reminder.avito.random.randrange", lambda _size: 0)
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(first, second),
            avito_proxy_rotation_enabled=True,
            avito_proxy_rotation_delay_seconds=0,
            avito_proxy_max_rotations=1,
        )
    )
    identity = client._ensure_browser_identity()
    routes: list[str | None] = []

    async def fake_start_browser() -> None:
        return None

    async def fake_start_session() -> None:
        return None

    async def fake_search(*_args, **_kwargs):
        current = client._avito_proxies.current
        routes.append(current)
        if current == first:
            raise AvitoNetworkError("proxy returned HTTP 502")
        return []

    monkeypatch.setattr(client, "_start_browser", fake_start_browser)
    monkeypatch.setattr(client, "_start_browser_session", fake_start_session)
    monkeypatch.setattr(client, "_search_browser_with_current_proxy", fake_search)

    result = asyncio.run(client._search_browser("https://www.avito.ru/moskva?q=test"))

    assert result == []
    assert routes == [first, second]
    assert client._avito_proxies.current == second
    assert client._ensure_browser_identity().identity_id == identity.identity_id
    assert (
        client._route_health.quarantine_remaining(
            client._route_health_key(first, use_current_route=False)
        )
        > 0
    )


def test_proxy_change_url_rejects_redirect_without_following_it(
    tmp_path,
    monkeypatch,
) -> None:
    requests: list[tuple[str, bool]] = []

    class Response:
        status = 302

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Session:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, url: str, *, allow_redirects: bool):
            requests.append((url, allow_redirects))
            return Response()

    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_proxy_change_url="https://rotate.example.test/secret",
        )
    )
    monkeypatch.setattr("avito_reminder.avito.aiohttp.ClientSession", Session)

    with pytest.raises(AvitoNetworkError, match="HTTP 302"):
        asyncio.run(client._call_proxy_change_url())

    assert requests == [("https://rotate.example.test/secret", False)]


def test_proxy_timeout_on_about_blank_rotates_without_screenshot(tmp_path) -> None:
    page = BlankTimeoutPageStub()
    client = AvitoClient(
        settings(
            tmp_path / "test.db",
            avito_transport="hybrid",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(
                "http://user:password@proxy.example.test:1000",
                "http://user:password@proxy2.example.test:1000",
            ),
            avito_proxy_rotation_enabled=True,
            avito_browser_headless=False,
        )
    )
    client._browser_context = SimpleNamespace(pages=[page])  # type: ignore[assignment]

    with pytest.raises(_AvitoProxyRotationRequired, match="about:blank") as raised:
        asyncio.run(
            client._search_browser_with_current_proxy(
                "https://www.avito.ru/moskva?q=test"
            )
        )

    assert page.closed is False
    assert page.screenshot_calls == 0
    assert page.status_content_calls == 1
    assert raised.value.replace_identity is False
    assert client._route_health.quarantine_remaining(client._route_health_key()) > 0
