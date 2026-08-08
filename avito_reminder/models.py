from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Search:
    id: int
    chat_id: int
    user_id: int
    query: str
    city: str
    price_min: int | None
    price_max: int | None
    interval_seconds: int
    url: str
    active: bool
    initialized: bool
    created_at: str
    last_checked_at: str | None
    next_check_at: str
    last_error: str | None
    failure_count: int


@dataclass(frozen=True, slots=True)
class AvitoItem:
    id: str
    title: str
    price: int | None
    url: str
    location: str | None = None
    image_url: str | None = None
