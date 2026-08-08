from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


def _as_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc
    if value < minimum:
        raise ValueError(f"{name} должен быть не меньше {minimum}")
    return value


def _proxy_url(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name}: некорректный адрес прокси") from exc
    if parsed.scheme.lower() not in {"http", "https", "socks4", "socks5"}:
        raise ValueError(f"{name}: поддерживаются http, https, socks4 и socks5")
    if not parsed.hostname or port is None:
        raise ValueError(f"{name}: укажите хост и порт прокси")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"{name}: path, query и fragment не поддерживаются")
    return raw


def _choice(name: str, default: str, allowed: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in allowed:
        variants = ", ".join(sorted(allowed))
        raise ValueError(f"{name}: ожидается одно из значений: {variants}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    scheduler_poll_seconds: int
    search_interval_seconds: int
    request_timeout_seconds: int
    request_retries: int
    max_results: int
    max_notifications_per_check: int
    notify_initial_results: bool
    telegram_proxy: str | None
    telegram_proxy_rdns: bool
    avito_cookie: str | None
    http_proxy: str | None
    avito_proxy_mode: str
    avito_proxy_rdns: bool
    avito_transport: str
    avito_http_impersonate: str
    avito_api_max_pages: int
    avito_browser_headless: bool
    avito_browser_profile_path: Path
    avito_chromium_executable: str | None
    avito_min_request_interval_seconds: int
    avito_request_jitter_seconds: int
    avito_page_reload_delay_seconds: int
    avito_error_reload_attempts: int
    avito_cooldown_seconds: int
    user_agent: str
    log_level: str


def load_settings(*, require_bot_token: bool = True) -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if require_bot_token and not token:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN. Скопируйте .env.example в .env "
            "и добавьте токен BotFather."
        )

    database_path = Path(os.getenv("DATABASE_PATH", "data/avito_reminder.db"))
    avito_proxy = _proxy_url("AVITO_PROXY") or _proxy_url("AVITO_HTTP_PROXY")
    avito_proxy_mode = _choice(
        "AVITO_PROXY_MODE",
        "fallback" if avito_proxy else "direct",
        {"direct", "proxy", "fallback"},
    )
    if avito_proxy_mode == "proxy" and not avito_proxy:
        raise ValueError("AVITO_PROXY_MODE=proxy требует заполненный AVITO_PROXY")
    return Settings(
        bot_token=token,
        database_path=database_path,
        scheduler_poll_seconds=_as_int("SCHEDULER_POLL_SECONDS", 15),
        search_interval_seconds=_as_int("SEARCH_INTERVAL_SECONDS", 900, minimum=60),
        request_timeout_seconds=_as_int("REQUEST_TIMEOUT_SECONDS", 25, minimum=5),
        request_retries=_as_int("REQUEST_RETRIES", 3),
        max_results=_as_int("MAX_RESULTS", 30),
        max_notifications_per_check=_as_int("MAX_NOTIFICATIONS_PER_CHECK", 5),
        notify_initial_results=_as_bool(os.getenv("NOTIFY_INITIAL_RESULTS"), True),
        telegram_proxy=_proxy_url("TELEGRAM_PROXY"),
        telegram_proxy_rdns=_as_bool(os.getenv("TELEGRAM_PROXY_RDNS"), True),
        avito_cookie=os.getenv("AVITO_COOKIE") or None,
        http_proxy=avito_proxy,
        avito_proxy_mode=avito_proxy_mode,
        avito_proxy_rdns=_as_bool(os.getenv("AVITO_PROXY_RDNS"), True),
        avito_transport=_choice(
            "AVITO_TRANSPORT",
            "hybrid",
            {"browser", "http", "hybrid"},
        ),
        avito_http_impersonate=os.getenv("AVITO_HTTP_IMPERSONATE", "chrome").strip()
        or "chrome",
        avito_api_max_pages=_as_int("AVITO_API_MAX_PAGES", 3),
        avito_browser_headless=_as_bool(os.getenv("AVITO_BROWSER_HEADLESS"), True),
        avito_browser_profile_path=Path(
            os.getenv("AVITO_BROWSER_PROFILE_PATH", "data/chromium-profile")
        ),
        avito_chromium_executable=os.getenv("AVITO_CHROMIUM_EXECUTABLE") or None,
        avito_min_request_interval_seconds=_as_int("AVITO_MIN_REQUEST_INTERVAL_SECONDS", 60),
        avito_request_jitter_seconds=_as_int("AVITO_REQUEST_JITTER_SECONDS", 30, minimum=0),
        avito_page_reload_delay_seconds=_as_int("AVITO_PAGE_RELOAD_DELAY_SECONDS", 90),
        avito_error_reload_attempts=_as_int("AVITO_ERROR_RELOAD_ATTEMPTS", 3),
        avito_cooldown_seconds=_as_int("AVITO_COOLDOWN_SECONDS", 10_800),
        user_agent=os.getenv(
            "AVITO_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
