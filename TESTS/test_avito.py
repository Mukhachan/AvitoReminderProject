import asyncio
import json
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
