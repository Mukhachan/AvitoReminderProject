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
    return _validate_proxy_url(name, raw)


def _validate_proxy_url(name: str, raw: str) -> str:
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


def _proxy_pool(path: Path | None, primary_proxy: str | None) -> tuple[str, ...]:
    proxies: list[str] = []
    if primary_proxy:
        proxies.append(primary_proxy)
    if path is not None:
        if not path.is_file():
            raise ValueError(f"AVITO_PROXY_POOL_FILE: файл не найден: {path}")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            proxy = _validate_proxy_url(
                f"AVITO_PROXY_POOL_FILE, строка {line_number}",
                value,
            )
            if proxy not in proxies:
                proxies.append(proxy)
    return tuple(proxies)


def _http_url(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name}: ожидается полный http/https URL")
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
    avito_proxy_pool: tuple[str, ...]
    avito_proxy_change_url: str | None
    avito_proxy_mode: str
    avito_proxy_rdns: bool
    avito_proxy_rotation_enabled: bool
    avito_proxy_rotate_after_reloads: int
    avito_proxy_rotation_delay_seconds: int
    avito_proxy_max_rotations: int
    avito_log_public_ip: bool
    avito_transport: str
    avito_http_impersonate: str
    avito_api_max_pages: int
    avito_browser_headless: bool
    avito_browser_profile_path: Path
    avito_chromium_executable: str | None
    avito_browser_stealth: bool
    avito_browser_snapshots: bool
    avito_identity_rotate_on_block: bool
    avito_new_user_per_session: bool
    avito_identity_rotate_on_browser_start: bool
    avito_proxy_rotate_on_browser_start: bool
    avito_browser_locale: str
    avito_browser_timezone: str
    avito_min_request_interval_seconds: int
    avito_request_jitter_seconds: int
    avito_page_reload_delay_seconds: int
    avito_page_reload_jitter_seconds: int
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
    raw_pool_path = os.getenv("AVITO_PROXY_POOL_FILE", "").strip()
    proxy_pool_path = Path(raw_pool_path) if raw_pool_path else None
    avito_proxy_pool = _proxy_pool(proxy_pool_path, avito_proxy)
    avito_proxy_change_url = _http_url("AVITO_PROXY_CHANGE_URL")
    avito_proxy_mode = _choice(
        "AVITO_PROXY_MODE",
        "fallback" if avito_proxy_pool or avito_proxy_change_url else "direct",
        {"direct", "proxy", "fallback"},
    )
    if avito_proxy_mode == "proxy" and not avito_proxy_pool:
        raise ValueError(
            "AVITO_PROXY_MODE=proxy требует AVITO_PROXY или AVITO_PROXY_POOL_FILE"
        )
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
        avito_proxy_pool=avito_proxy_pool,
        avito_proxy_change_url=avito_proxy_change_url,
        avito_proxy_mode=avito_proxy_mode,
        avito_proxy_rdns=_as_bool(os.getenv("AVITO_PROXY_RDNS"), True),
        avito_proxy_rotation_enabled=_as_bool(
            os.getenv("AVITO_PROXY_ROTATION_ENABLED"),
            bool(avito_proxy_pool or avito_proxy_change_url),
        ),
        avito_proxy_rotate_after_reloads=_as_int(
            "AVITO_PROXY_ROTATE_AFTER_RELOADS", 1
        ),
        avito_proxy_rotation_delay_seconds=_as_int(
            "AVITO_PROXY_ROTATION_DELAY_SECONDS", 15,
            minimum=0,
        ),
        avito_proxy_max_rotations=_as_int("AVITO_PROXY_MAX_ROTATIONS", 5),
        avito_log_public_ip=_as_bool(os.getenv("AVITO_LOG_PUBLIC_IP"), True),
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
        avito_browser_stealth=_as_bool(os.getenv("AVITO_BROWSER_STEALTH"), True),
        avito_browser_snapshots=_as_bool(
            os.getenv("AVITO_BROWSER_SNAPSHOTS"), True
        ),
        avito_identity_rotate_on_block=_as_bool(
            os.getenv("AVITO_IDENTITY_ROTATE_ON_BLOCK"), True
        ),
        avito_new_user_per_session=_as_bool(
            os.getenv("AVITO_NEW_USER_PER_SESSION"), True
        ),
        avito_identity_rotate_on_browser_start=_as_bool(
            os.getenv("AVITO_IDENTITY_ROTATE_ON_BROWSER_START"), True
        ),
        avito_proxy_rotate_on_browser_start=_as_bool(
            os.getenv("AVITO_PROXY_ROTATE_ON_BROWSER_START"), True
        ),
        avito_browser_locale=os.getenv("AVITO_BROWSER_LOCALE", "ru-RU").strip()
        or "ru-RU",
        avito_browser_timezone=os.getenv(
            "AVITO_BROWSER_TIMEZONE", "Europe/Moscow"
        ).strip()
        or "Europe/Moscow",
        avito_min_request_interval_seconds=_as_int("AVITO_MIN_REQUEST_INTERVAL_SECONDS", 60),
        avito_request_jitter_seconds=_as_int("AVITO_REQUEST_JITTER_SECONDS", 30, minimum=0),
        avito_page_reload_delay_seconds=_as_int("AVITO_PAGE_RELOAD_DELAY_SECONDS", 90),
        avito_page_reload_jitter_seconds=_as_int(
            "AVITO_PAGE_RELOAD_JITTER_SECONDS", 30, minimum=0
        ),
        avito_error_reload_attempts=_as_int("AVITO_ERROR_RELOAD_ATTEMPTS", 3),
        avito_cooldown_seconds=_as_int("AVITO_COOLDOWN_SECONDS", 10_800),
        user_agent=os.getenv(
            "AVITO_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
