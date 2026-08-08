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
        "avito_proxy_mode": "direct",
        "avito_proxy_rdns": True,
        "avito_transport": "http",
        "avito_browser_headless": True,
        "avito_browser_profile_path": database_path.parent / "chromium-profile",
        "avito_chromium_executable": None,
        "avito_min_request_interval_seconds": 1,
        "avito_request_jitter_seconds": 0,
        "avito_page_reload_delay_seconds": 90,
        "user_agent": "test-agent",
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]
