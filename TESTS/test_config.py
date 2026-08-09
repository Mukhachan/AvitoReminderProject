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
    monkeypatch.setenv("AVITO_HTTP_IMPERSONATE", "chrome")
    monkeypatch.setenv("AVITO_API_MAX_PAGES", "4")
    monkeypatch.setenv("AVITO_BROWSER_HEADLESS", "true")
    monkeypatch.setenv("AVITO_BROWSER_PROFILE_PATH", "data/test-browser-profile")
    monkeypatch.setenv("AVITO_MIN_REQUEST_INTERVAL_SECONDS", "25")
    monkeypatch.setenv("AVITO_REQUEST_JITTER_SECONDS", "5")
    monkeypatch.setenv("AVITO_PAGE_RELOAD_DELAY_SECONDS", "91")
    monkeypatch.setenv("AVITO_ERROR_RELOAD_ATTEMPTS", "4")
    monkeypatch.setenv("AVITO_COOLDOWN_SECONDS", "14400")

    settings = load_settings()

    assert settings.telegram_proxy == "socks5://127.0.0.1:20808"
    assert settings.telegram_proxy_rdns is True
    assert settings.http_proxy == "socks5://127.0.0.1:20808"
    assert settings.avito_proxy_mode == "fallback"
    assert settings.avito_proxy_rdns is True
    assert settings.avito_transport == "browser"
    assert settings.avito_http_impersonate == "chrome"
    assert settings.avito_api_max_pages == 4
    assert settings.avito_browser_headless is True
    assert settings.avito_browser_profile_path.as_posix() == "data/test-browser-profile"
    assert settings.avito_min_request_interval_seconds == 25
    assert settings.avito_request_jitter_seconds == 5
    assert settings.avito_page_reload_delay_seconds == 91
    assert settings.avito_error_reload_attempts == 4
    assert settings.avito_cooldown_seconds == 14_400


def test_settings_reject_invalid_proxy(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "ftp://127.0.0.1:20808")
    with pytest.raises(ValueError, match="поддерживаются"):
        load_settings()


def test_settings_load_avito_proxy_pool_and_rotation(monkeypatch, tmp_path) -> None:
    pool_path = tmp_path / "avito-proxies.txt"
    pool_path.write_text(
        "# Один sticky IP на строку\n"
        "http://user:password@first.proxy.test:1000\n"
        "http://user:password@second.proxy.test:1000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("AVITO_PROXY", "")
    monkeypatch.setenv("AVITO_HTTP_PROXY", "")
    monkeypatch.setenv("AVITO_PROXY_MODE", "fallback")
    monkeypatch.setenv("AVITO_PROXY_POOL_FILE", str(pool_path))
    monkeypatch.setenv("AVITO_PROXY_CHANGE_URL", "https://rotate.example.test/key")
    monkeypatch.setenv("AVITO_PROXY_ROTATION_ENABLED", "true")
    monkeypatch.setenv("AVITO_PROXY_ROTATE_AFTER_RELOADS", "2")
    monkeypatch.setenv("AVITO_PROXY_ROTATION_DELAY_SECONDS", "7")
    monkeypatch.setenv("AVITO_PROXY_MAX_ROTATIONS", "4")
    monkeypatch.setenv("AVITO_LOG_PUBLIC_IP", "false")

    settings = load_settings()

    assert settings.avito_proxy_pool == (
        "http://user:password@first.proxy.test:1000",
        "http://user:password@second.proxy.test:1000",
    )
    assert settings.avito_proxy_change_url == "https://rotate.example.test/key"
    assert settings.avito_proxy_rotation_enabled is True
    assert settings.avito_proxy_rotate_after_reloads == 2
    assert settings.avito_proxy_rotation_delay_seconds == 7
    assert settings.avito_proxy_max_rotations == 4
    assert settings.avito_log_public_ip is False


def test_telegram_transport_applies_rdns(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_PROXY", "socks5://127.0.0.1:20808")
    monkeypatch.setenv("TELEGRAM_PROXY_RDNS", "false")
    settings = load_settings()
    session = create_telegram_session(settings)
    assert session._connector_init["rdns"] is False
    asyncio.run(session.close())
