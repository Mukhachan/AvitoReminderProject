import pytest

from avito_reminder.models import Search
from avito_reminder.telegram import (
    _confirmation_text,
    _format_interval,
    _parse_interval,
    _parse_price,
    _search_keyboard,
    _search_text,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("45 000 ₽", 45_000),
        ("Без ограничения", None),
        ("0", None),
    ],
)
def test_parse_price_for_wizard(value, expected) -> None:
    assert _parse_price(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15 минут", 900),
        ("45 минут", 2700),
        ("2 часа", 7200),
        ("24 часа", 86_400),
    ],
)
def test_parse_interval_for_wizard(value, expected) -> None:
    assert _parse_interval(value) == expected


def test_parse_interval_rejects_too_frequent_checks() -> None:
    with pytest.raises(ValueError, match="15 минут"):
        _parse_interval("5 минут")


def test_search_card_contains_interval_and_actions() -> None:
    search = Search(
        id=7,
        chat_id=10,
        user_id=20,
        query="iPhone 13",
        city="Москва",
        price_min=30_000,
        price_max=50_000,
        interval_seconds=1800,
        url="https://www.avito.ru/moskva?q=iPhone+13",
        active=True,
        initialized=False,
        created_at="2026-01-01T00:00:00+00:00",
        last_checked_at=None,
        next_check_at="2026-01-01T00:00:00+00:00",
        last_error=None,
        failure_count=0,
    )

    text = _search_text(search)
    keyboard = _search_keyboard(search)

    assert "каждые 30 минут" in text.lower()
    assert keyboard.inline_keyboard[0][0].url == search.url
    assert keyboard.inline_keyboard[1][1].callback_data == "search:delete-ask:7"


def test_confirmation_text_summarizes_all_answers() -> None:
    text = _confirmation_text(
        {
            "query": "Велосипед",
            "city": "Казань",
            "price_min": 10_000,
            "price_max": None,
            "interval_seconds": 3600,
        }
    )

    assert "Велосипед" in text
    assert "от 10 000" in text
    assert _format_interval(3600) in text
