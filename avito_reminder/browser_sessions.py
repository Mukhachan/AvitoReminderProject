from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from playwright.async_api import Browser, BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

from .browser_identity import BrowserIdentity, stealth_init_script
from .diagnostics import prune_browser_session_snapshots, write_private_json

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
    webdriver: navigator.webdriver,
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
    write_private_json(path, snapshot)
    prune_browser_session_snapshots(path.parent)


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

    async def create_session(
        self,
        identity: BrowserIdentity,
        *,
        storage_state: Path | None = None,
    ) -> BrowserSession:
        options: dict[str, object] = {
            "locale": identity.locale,
            "timezone_id": identity.timezone_id,
            "viewport": identity.viewport,
            "screen": identity.screen,
            "device_scale_factor": identity.device_scale_factor,
            "accept_downloads": False,
            "service_workers": "allow",
        }
        if self.proxy is not None:
            options["proxy"] = self.proxy
        if storage_state is not None:
            options["storage_state"] = str(storage_state)
        if self.stealth:
            # Only the explicitly enabled experimental mode overrides browser/OS
            # signals.  Normal production sessions use Chromium's real UA/platform.
            options.update(
                {
                    "user_agent": identity.user_agent,
                    "is_mobile": identity.is_mobile,
                    "has_touch": identity.is_mobile,
                }
            )

        context = await self.browser.new_context(
            **options,
        )
        try:
            if self.stealth:
                await context.set_extra_http_headers(identity.http_headers)
                await context.add_init_script(script=stealth_init_script(identity))
            page = await context.new_page()
        except BaseException:
            with suppress(PlaywrightError):
                await context.close()
            raise
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
            with suppress(PlaywrightError):
                await session.context.close()
            logger.info("Изолированная Chromium-сессия закрыта: session=%s", session.session_id)
