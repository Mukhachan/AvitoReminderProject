import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from avito_reminder.avito import (
    AvitoBlockedError,
    AvitoClient,
    AvitoError,
    AvitoNetworkError,
    AvitoParseError,
    build_search_url,
    city_slug,
    parse_search_html,
)

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


def test_browser_transport_uses_direct_chromium_route(tmp_path) -> None:
    client = BrowserStubClient(
        settings(
            tmp_path / "test.db",
            avito_transport="browser",
        )
    )

    assert asyncio.run(client.search("https://www.avito.ru/moskva")) == []
    assert client.last_route == "chromium-direct"


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
