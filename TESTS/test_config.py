import asyncio

import pytest

from avito_reminder.config import load_settings
from avito_reminder.telegram_transport import create_telegram_session


def test_settings_split_telegram_and_avito_proxies(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "socks5://127.0.0.1:20808")
    monkeypatch.setenv("TELEGRAM_PROXY_RDNS", "true")
    monkeypatch.setenv("AVITO_PROXY", "socks5://127.0.0.1:20808")
    monkeypatch.setenv("AVITO_PROXY_MODE", "fallback")
    monkeypatch.setenv("AVITO_PROXY_RDNS", "true")
    monkeypatch.setenv("AVITO_TRANSPORT", "browser")
    monkeypatch.setenv("AVITO_BROWSER_HEADLESS", "true")
    monkeypatch.setenv("AVITO_BROWSER_PROFILE_PATH", "data/test-browser-profile")
    monkeypatch.setenv("AVITO_MIN_REQUEST_INTERVAL_SECONDS", "25")
    monkeypatch.setenv("AVITO_REQUEST_JITTER_SECONDS", "5")

    settings = load_settings()

    assert settings.telegram_proxy == "socks5://127.0.0.1:20808"
    assert settings.telegram_proxy_rdns is True
    assert settings.http_proxy == "socks5://127.0.0.1:20808"
    assert settings.avito_proxy_mode == "fallback"
    assert settings.avito_proxy_rdns is True
    assert settings.avito_transport == "browser"
    assert settings.avito_browser_headless is True
    assert settings.avito_browser_profile_path.as_posix() == "data/test-browser-profile"
    assert settings.avito_min_request_interval_seconds == 25
    assert settings.avito_request_jitter_seconds == 5


def test_settings_reject_invalid_proxy(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "ftp://127.0.0.1:20808")
    with pytest.raises(ValueError, match="поддерживаются"):
        load_settings()


def test_telegram_transport_applies_rdns(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "socks5://127.0.0.1:20808")
    monkeypatch.setenv("TELEGRAM_PROXY_RDNS", "false")
    settings = load_settings()
    session = create_telegram_session(settings)
    assert session._connector_init["rdns"] is False
    asyncio.run(session.close())
