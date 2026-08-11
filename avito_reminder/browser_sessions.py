from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from playwright.async_api import Browser, BrowserContext, Page

from .browser_identity import BrowserIdentity, stealth_init_script

logger = logging.getLogger(__name__)

_SNAPSHOT_SCRIPT = """
async () => {
  const indexedDBDatabases = indexedDB.databases
    ? await indexedDB.databases()
    : [];
  const cacheStorage = typeof caches !== 'undefined' ? await caches.keys() : [];
  const serviceWorkers = 'serviceWorker' in navigator
    ? (await navigator.serviceWorker.getRegistrations()).map((item) => item.scope)
    : [];
  return {
    userAgent: navigator.userAgent,
    language: navigator.language,
    languages: Array.from(navigator.languages),
    platform: navigator.platform,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory ?? null,
    maxTouchPoints: navigator.maxTouchPoints,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio
    },
    screen: {
      width: screen.width,
      height: screen.height,
      colorDepth: screen.colorDepth,
      pixelDepth: screen.pixelDepth
    },
    indexedDB: indexedDBDatabases,
    cacheStorage,
    serviceWorkers
  };
}
"""

_STORAGE_AUDIT_SCRIPT = """
async (marker) => ({
  localStorage: localStorage.getItem(marker),
  sessionStorage: sessionStorage.getItem(marker),
  indexedDB: indexedDB.databases ? await indexedDB.databases() : [],
  cacheStorage: typeof caches !== 'undefined' ? await caches.keys() : [],
  serviceWorkers: 'serviceWorker' in navigator
    ? (await navigator.serviceWorker.getRegistrations()).map((item) => item.scope)
    : []
})
"""


@dataclass(frozen=True, slots=True)
class BrowserSession:
    session_id: str
    context: BrowserContext
    page: Page
    identity: BrowserIdentity


async def collect_browser_snapshot(page: Page) -> dict[str, Any]:
    """Collect observable browser and storage signals for diagnostics."""
    snapshot = await page.evaluate(_SNAPSHOT_SCRIPT)
    if not isinstance(snapshot, dict):
        raise TypeError("Chromium вернул некорректный browser snapshot")
    return snapshot


def save_browser_snapshot(snapshot: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(snapshot), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def diff_browser_snapshots(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    prefix: str = "",
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    for key in sorted(set(left) | set(right)):
        path = f"{prefix}.{key}" if prefix else key
        left_value = left.get(key)
        right_value = right.get(key)
        if isinstance(left_value, Mapping) and isinstance(right_value, Mapping):
            differences.extend(
                diff_browser_snapshots(left_value, right_value, path)
            )
        elif left_value != right_value:
            differences.append(
                {"path": path, "left": left_value, "right": right_value}
            )
    return differences


async def inspect_browser_storage(page: Page, marker: str) -> dict[str, Any]:
    state = await page.evaluate(_STORAGE_AUDIT_SCRIPT, marker)
    if not isinstance(state, dict):
        raise TypeError("Chromium вернул некорректный storage audit")
    return state


def storage_leaks(state: Mapping[str, Any], marker: str) -> list[str]:
    leaks: list[str] = []
    if state.get("localStorage") is not None:
        leaks.append("localStorage")
    if state.get("sessionStorage") is not None:
        leaks.append("sessionStorage")
    for field in ("indexedDB", "cacheStorage", "serviceWorkers"):
        values = state.get(field)
        if isinstance(values, list) and any(marker in str(value) for value in values):
            leaks.append(field)
    return leaks


class BrowserIdentityManager:
    """Create short-lived, mutually isolated contexts in one Chromium process."""

    def __init__(
        self,
        browser: Browser,
        *,
        proxy: dict[str, str] | None = None,
        stealth: bool = True,
    ) -> None:
        self.browser = browser
        self.proxy = proxy
        self.stealth = stealth

    async def create_session(self, identity: BrowserIdentity) -> BrowserSession:
        context = await self.browser.new_context(
            proxy=self.proxy,
            user_agent=identity.user_agent,
            locale=identity.locale,
            timezone_id=identity.timezone_id,
            viewport=identity.viewport,
            screen=identity.screen,
            device_scale_factor=identity.device_scale_factor,
            is_mobile=identity.is_mobile,
            has_touch=identity.is_mobile,
            accept_downloads=False,
            service_workers="allow",
        )
        await context.set_extra_http_headers(identity.http_headers)
        if self.stealth:
            await context.add_init_script(script=stealth_init_script(identity))
        page = await context.new_page()
        session = BrowserSession(
            session_id=str(uuid4()),
            context=context,
            page=page,
            identity=identity,
        )
        logger.info(
            "Изолированная Chromium-сессия создана: session=%s identity=%s",
            session.session_id,
            identity.identity_id,
        )
        return session

    @asynccontextmanager
    async def open_session(
        self,
        identity: BrowserIdentity,
    ) -> AsyncIterator[BrowserSession]:
        session = await self.create_session(identity)
        try:
            yield session
        finally:
            await session.context.close()
            logger.info("Изолированная Chromium-сессия закрыта: session=%s", session.session_id)
