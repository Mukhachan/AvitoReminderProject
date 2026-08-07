from __future__ import annotations

from urllib.parse import urlsplit

from aiogram.client.session.aiohttp import AiohttpSession

from .config import Settings


def create_telegram_session(settings: Settings, *, timeout: int = 60) -> AiohttpSession:
    """Create a Telegram session with an optional HTTP/SOCKS proxy."""
    session = AiohttpSession(proxy=settings.telegram_proxy, timeout=timeout)
    if settings.telegram_proxy:
        scheme = urlsplit(settings.telegram_proxy).scheme.lower()
        if scheme in {"socks4", "socks5"}:
            # Aiogram defaults to remote DNS for SOCKS. Keep this configurable
            # because some local VPN gateways require DNS on the Raspberry Pi.
            session._connector_init["rdns"] = settings.telegram_proxy_rdns
    return session
