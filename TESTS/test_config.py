import asyncio

import pytest

from avito_reminder.config import load_settings
from avito_reminder.telegram_transport import create_telegram_session


def test_settings_split_telegram_and_avito_proxies(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "socks5://127.0.0.1:10808")
    monkeypatch.setenv("TELEGRAM_PROXY_RDNS", "true")
    monkeypatch.delenv("AVITO_HTTP_PROXY", raising=False)

    settings = load_settings()

    assert settings.telegram_proxy == "socks5://127.0.0.1:10808"
    assert settings.telegram_proxy_rdns is True
    assert settings.http_proxy is None


def test_settings_reject_invalid_proxy(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "ftp://127.0.0.1:10808")
    with pytest.raises(ValueError, match="поддерживаются"):
        load_settings()


def test_telegram_transport_applies_rdns(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "socks5://127.0.0.1:10808")
    monkeypatch.setenv("TELEGRAM_PROXY_RDNS", "false")
    settings = load_settings()
    session = create_telegram_session(settings)
    assert session._connector_init["rdns"] is False
    asyncio.run(session.close())
