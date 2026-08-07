"""Compatibility exports for the upgraded Avito client."""

from avito_reminder.avito import (
    AvitoBlockedError,
    AvitoClient,
    AvitoError,
    AvitoNetworkError,
    AvitoParseError,
    build_search_url,
    parse_search_html,
)

__all__ = [
    "AvitoBlockedError",
    "AvitoClient",
    "AvitoError",
    "AvitoNetworkError",
    "AvitoParseError",
    "build_search_url",
    "parse_search_html",
]
