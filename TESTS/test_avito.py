import json
from urllib.parse import parse_qs, urlparse

import pytest

from avito_reminder.avito import (
    AvitoBlockedError,
    AvitoParseError,
    build_search_url,
    city_slug,
    parse_search_html,
)


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
