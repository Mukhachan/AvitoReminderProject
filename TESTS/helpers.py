from pathlib import Path

from avito_reminder.config import Settings


def settings(database_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "bot_token": "123456:test-token",
        "database_path": database_path,
        "scheduler_poll_seconds": 1,
        "search_interval_seconds": 60,
        "request_timeout_seconds": 5,
        "request_retries": 1,
        "max_results": 30,
        "max_notifications_per_check": 5,
        "notify_initial_results": True,
        "telegram_proxy": None,
        "telegram_proxy_rdns": True,
        "avito_cookie": None,
        "http_proxy": None,
        "avito_proxy_pool": (),
        "avito_proxy_change_url": None,
        "avito_proxy_mode": "direct",
        "avito_proxy_rdns": True,
        "avito_proxy_rotation_enabled": False,
        "avito_proxy_rotate_after_reloads": 1,
        "avito_proxy_rotation_delay_seconds": 15,
        "avito_proxy_max_rotations": 5,
        "avito_log_public_ip": True,
        "avito_transport": "http",
        "avito_http_impersonate": "chrome",
        "avito_api_max_pages": 3,
        "avito_browser_headless": True,
        "avito_browser_profile_path": database_path.parent / "chromium-profile",
        "avito_chromium_executable": None,
        "avito_browser_stealth": True,
        "avito_browser_snapshots": True,
        "avito_identity_rotate_on_block": True,
        "avito_browser_locale": "ru-RU",
        "avito_browser_timezone": "Europe/Moscow",
        "avito_min_request_interval_seconds": 1,
        "avito_request_jitter_seconds": 0,
        "avito_page_reload_delay_seconds": 90,
        "avito_page_reload_jitter_seconds": 0,
        "avito_error_reload_attempts": 3,
        "avito_cooldown_seconds": 10_800,
        "user_agent": "test-agent",
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]
