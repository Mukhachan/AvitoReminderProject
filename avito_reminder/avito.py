from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import random
import re
import shutil
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlsplit

import aiohttp
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup, Tag
from curl_cffi.requests import AsyncSession as CurlAsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestError
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from .avito_mfe import (
    AvitoPageState,
    catalog_from_api_response,
    extract_page_state,
    parse_api_response,
)
from .browser_identity import (
    BrowserIdentity,
    generate_browser_identity,
    load_browser_identity,
    resolve_http_impersonate,
    save_browser_identity,
)
from .browser_sessions import (
    BrowserIdentityManager,
    BrowserSession,
    collect_browser_snapshot,
    save_browser_snapshot,
)
from .config import Settings
from .diagnostics import (
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    harden_file_permissions,
    maintain_browser_storage_directory,
    prune_avito_diagnostic_bundles,
    write_private_json,
    write_private_text,
)
from .models import AvitoItem

logger = logging.getLogger(__name__)

AVITO_BASE_URL = "https://www.avito.ru"
PUBLIC_IP_CHECK_URL = "https://api.ipify.org?format=json"
AVITO_BLOCK_HTTP_STATUSES = frozenset({403, 429})
AVITO_CAPTCHA_MARKERS = (
    "нажмите для подтверждения",
    "продолжить для решения капчи",
    'data-marker="captcha"',
    "captcha challenge",
)
AVITO_TRANSIENT_IP_PROBLEM_MARKERS = (
    "доступ ограничен: проблема с ip",
)
AVITO_IMMEDIATE_RESTART_MARKERS = (
    "блокировка ip",
    *AVITO_CAPTCHA_MARKERS,
)
AVITO_BLOCK_MARKERS = (
    *AVITO_TRANSIENT_IP_PROBLEM_MARKERS,
    *AVITO_IMMEDIATE_RESTART_MARKERS,
    "too many requests",
)
AVITO_HOME_PAGE_NAME = "главная страница"
AVITO_SEARCH_PAGE_NAME = "страница поиска"
AVITO_HOME_CATEGORY_MARKERS = (
    "авто",
    "недвижимость",
    "услуги",
    "электроника",
    "работа",
    "запчасти",
)
AVITO_HOME_READY_SCRIPT = """
() => {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity || "1") > 0 && rect.width > 0 && rect.height > 0;
  };
  const visible = (selector) =>
    Array.from(document.querySelectorAll(selector)).some(isVisible);
  const visibleText = (selector, expected) =>
    Array.from(document.querySelectorAll(selector)).some((element) => {
      if (!isVisible(element)) return false;
      const text = (element.textContent || "").replace(/\\s+/g, " ").trim().toLowerCase();
      return expected.some((value) => text.includes(value));
    });

  const blockIsVisible = visible('[data-marker="captcha"]') || visibleText(
    "h1, h2, h3, p, button",
    [
      "доступ ограничен: проблема с ip",
      "блокировка ip",
      "нажмите для подтверждения",
      "продолжить для решения капчи",
    ],
  );
  if (blockIsVisible) return false;

  const searchIsVisible = visible(
    '[data-marker="search-form/suggest/input"], ' +
    'input[placeholder*="Поиск по объявлениям" i]',
  );
  const submitIsVisible = visible('[data-marker="search-form/submit-button"]') ||
    visibleText("button", ["найти"]);
  const categoryNames = [
    "авто",
    "недвижимость",
    "услуги",
    "электроника",
    "работа",
    "запчасти",
  ];
  const categoryCount = categoryNames.filter((name) =>
    visibleText("a, button, h2, h3", [name]),
  ).length;
  return searchIsVisible && submitIsVisible && categoryCount >= 3;
}
"""
AVITO_HOME_TERMINAL_SCRIPT = """
() => {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity || "1") > 0 && rect.width > 0 && rect.height > 0;
  };
  const visible = (selector) =>
    Array.from(document.querySelectorAll(selector)).some(isVisible);
  const visibleText = (selector, expected) =>
    Array.from(document.querySelectorAll(selector)).some((element) => {
      if (!isVisible(element)) return false;
      const text = (element.textContent || "").replace(/\\s+/g, " ").trim().toLowerCase();
      return expected.some((value) => text.includes(value));
    });

  const blocked = visible('[data-marker="captcha"]') || visibleText(
    "h1, h2, h3, p, button",
    [
      "доступ ограничен: проблема с ip",
      "блокировка ip",
      "нажмите для подтверждения",
      "продолжить для решения капчи",
    ],
  );
  const search = visible(
    '[data-marker="search-form/suggest/input"], ' +
    'input[placeholder*="Поиск по объявлениям" i]',
  );
  const submit = visible('[data-marker="search-form/submit-button"]') ||
    visibleText("button", ["найти"]);
  const categories = [
    "авто",
    "недвижимость",
    "услуги",
    "электроника",
    "работа",
    "запчасти",
  ].filter((name) => visibleText("a, button, h2, h3", [name])).length;
  return blocked || (search && submit && categories >= 3);
}
"""
AVITO_SEARCH_READY_SCRIPT = """
() => {
  const current = new URL(window.location.href);
  if (!current.searchParams.get("q") || current.hash.toLowerCase() === "#block") {
    return false;
  }
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity || "1") > 0 && rect.width > 0 && rect.height > 0;
  };
  const visible = (selector) =>
    Array.from(document.querySelectorAll(selector)).some(isVisible);
  const visibleText = (selector, expected) =>
    Array.from(document.querySelectorAll(selector)).some((element) => {
      if (!isVisible(element)) return false;
      const text = (element.textContent || "").replace(/\\s+/g, " ").trim().toLowerCase();
      return expected.some((value) => text.includes(value));
    });
  const blockIsVisible = visible('[data-marker="captcha"]') || visibleText(
    "h1, h2, h3, p, button",
    [
      "доступ ограничен: проблема с ip",
      "блокировка ip",
      "нажмите для подтверждения",
      "продолжить для решения капчи",
    ],
  );
  if (blockIsVisible) return false;
  return visible(
    '[data-marker="item"], ' +
    '[data-item-id][itemtype*="Product"], ' +
    '[data-marker="search-results/empty"]',
  ) || visibleText(
    'main, [data-marker="catalog-serp"]',
    ["ничего не найдено", "объявлений не найдено", "нет подходящих объявлений"],
  );
}
"""
AVITO_SEARCH_TERMINAL_SCRIPT = """
() => {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity || "1") > 0 && rect.width > 0 && rect.height > 0;
  };
  const visible = (selector) =>
    Array.from(document.querySelectorAll(selector)).some(isVisible);
  const visibleText = (selector, expected) =>
    Array.from(document.querySelectorAll(selector)).some((element) => {
      if (!isVisible(element)) return false;
      const text = (element.textContent || "").replace(/\\s+/g, " ").trim().toLowerCase();
      return expected.some((value) => text.includes(value));
    });

  const blocked = visible('[data-marker="captcha"]') || visibleText(
    "h1, h2, h3, p, button",
    [
      "доступ ограничен: проблема с ip",
      "блокировка ip",
      "нажмите для подтверждения",
      "продолжить для решения капчи",
    ],
  );
  const result = visible(
    '[data-marker="item"], ' +
    '[data-item-id][itemtype*="Product"], ' +
    '[data-marker="search-results/empty"]',
  ) || visibleText(
    'main, [data-marker="catalog-serp"]',
    ["ничего не найдено", "объявлений не найдено", "нет подходящих объявлений"],
  );
  return blocked || result;
}
"""
AVITO_SITE_DATA_CLEAR_SCRIPT = """
async () => {
  localStorage.clear();
  sessionStorage.clear();
  if (window.caches) {
    for (const key of await window.caches.keys()) await window.caches.delete(key);
  }
  if (window.indexedDB?.databases) {
    for (const database of await window.indexedDB.databases()) {
      if (database.name) window.indexedDB.deleteDatabase(database.name);
    }
  }
}
"""


def _is_blocked_html(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in AVITO_BLOCK_MARKERS)


def _is_captcha_html(html: str) -> bool:
    # The transient IP page itself contains a help link/button whose text mentions
    # solving a captcha.  Its explicit heading is the authoritative state: this
    # page must receive the configured wait-and-reload treatment, not an immediate
    # identity/proxy restart.
    if _is_transient_ip_problem_html(html):
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in AVITO_CAPTCHA_MARKERS)


def _is_transient_ip_problem_html(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in AVITO_TRANSIENT_IP_PROBLEM_MARKERS)


def _requires_immediate_restart_html(html: str) -> bool:
    if _is_transient_ip_problem_html(html):
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in AVITO_IMMEDIATE_RESTART_MARKERS)


def _is_blocked_page(status: int | None, html: str) -> bool:
    return status in AVITO_BLOCK_HTTP_STATUSES or _is_blocked_html(html)


def _is_avito_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    return hostname == "avito.ru" or hostname.endswith(".avito.ru")


def _is_avito_page_ready(status: int | None, html: str, url: str) -> bool:
    return (
        status is not None
        and status < 400
        and _is_avito_url(url)
        and not _is_blocked_page(status, html)
    )


def _looks_like_loaded_avito_home_html(html: str) -> bool:
    """Recognize the populated home page even if stale block text remains in HTML."""
    soup = BeautifulSoup(html, "html.parser")
    search_input = soup.select_one('[data-marker="search-form/suggest/input"]')
    if search_input is None:
        search_input = next(
            (
                tag
                for tag in soup.find_all("input")
                if "поиск по объявлениям"
                in str(tag.get("placeholder", "")).strip().lower()
            ),
            None,
        )
    submit_button = soup.select_one('[data-marker="search-form/submit-button"]')
    page_text = " ".join(soup.stripped_strings).lower()
    has_submit = submit_button is not None or re.search(r"\bнайти\b", page_text) is not None
    category_count = sum(
        marker in page_text for marker in AVITO_HOME_CATEGORY_MARKERS
    )
    return search_input is not None and has_submit and category_count >= 3


async def _is_visually_loaded_avito_home(
    page: Page,
    html: str,
    *,
    wait_timeout_ms: int = 0,
) -> bool:
    """Prefer visible DOM state so hidden/stale block nodes cannot cause a false block."""
    try:
        if bool(await page.evaluate(AVITO_HOME_READY_SCRIPT)):
            return True
        if wait_timeout_ms > 0:
            await page.wait_for_function(
                AVITO_HOME_READY_SCRIPT,
                timeout=wait_timeout_ms,
            )
            return True
    except (AttributeError, PlaywrightError):
        return _looks_like_loaded_avito_home_html(html)
    return False


def _looks_like_loaded_avito_search_html(html: str) -> bool:
    """Recognize a populated or explicitly empty SERP despite stale hidden text."""
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.select_one(
            '[data-marker="catalog-serp"], '
            '[data-marker="item"], '
            '[data-item-id][itemtype*="Product"], '
            '[data-marker="search-results/empty"]'
        )
        or extract_page_state(html) is not None
    )


async def _is_visually_loaded_avito_search(
    page: Page,
    html: str,
    *,
    wait_timeout_ms: int = 0,
) -> bool:
    """Use visible SERP state so a hidden stale block node cannot win."""
    try:
        if bool(await page.evaluate(AVITO_SEARCH_READY_SCRIPT)):
            return True
        if wait_timeout_ms > 0:
            await page.wait_for_function(
                AVITO_SEARCH_READY_SCRIPT,
                timeout=wait_timeout_ms,
            )
            return True
    except PlaywrightTimeoutError:
        return False
    except (AttributeError, PlaywrightError):
        return _looks_like_loaded_avito_search_html(html)
    return False


def _retry_after_seconds(headers: Mapping[str, object] | None) -> int | None:
    if not headers:
        return None
    raw = next(
        (value for key, value in headers.items() if key.lower() == "retry-after"),
        None,
    )
    if raw is None:
        return None
    value = str(raw).strip()
    try:
        return max(1, int(value))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    return max(1, math.ceil((target - datetime.now(UTC)).total_seconds()))


def _has_target_search_query(current_url: str, target_url: str) -> bool:
    current = urlsplit(current_url)
    target = urlsplit(target_url)
    current_query = parse_qs(current.query)
    target_query = parse_qs(target.query)
    # Avito may remove or normalise the sort parameter while preserving the same
    # search.  Query text and price filters are the semantic parts generated by
    # build_search_url().  A generic city search may be canonicalised into one
    # category segment, but deeper/unrelated paths are not accepted blindly.
    significant_keys = {"q", "pmin", "pmax"} & set(target_query)
    current_path = [part for part in current.path.split("/") if part]
    target_path = [part for part in target.path.split("/") if part]
    return bool(
        _is_avito_url(current_url)
        and current.fragment.lower() != "block"
        and target_query.get("q")
        and current_path
        and target_path
        and current_path[0] == target_path[0]
        and (
            current_path == target_path
            or len(target_path) == 1
            and len(current_path) == 2
        )
        and all(current_query.get(key) == target_query.get(key) for key in significant_keys)
    )


def resolve_chromium_executable(settings: Settings) -> str | None:
    """Return an explicit or system Chromium path, otherwise use Playwright's build."""
    if settings.avito_chromium_executable:
        return settings.avito_chromium_executable
    for executable in ("chromium", "chromium-browser", "google-chrome"):
        resolved = shutil.which(executable)
        if resolved:
            return resolved
    return None


class AvitoError(RuntimeError):
    """Base error raised by the Avito client."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_path: Path | None = None,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.diagnostic_path = diagnostic_path
        self.retry_after_seconds = retry_after_seconds


class AvitoNetworkError(AvitoError):
    """Avito could not be reached."""


class AvitoSessionError(AvitoError):
    """The current Avito session is not accepted; this is not an IP rotation signal."""


class AvitoBlockedError(AvitoError):
    """Avito requested a captcha or blocked the current IP."""

    rotation_planned: bool | None = None


class AvitoRateLimitedError(AvitoBlockedError):
    """Avito or the local request budget requires a pause without rotating IP."""


class AvitoCaptchaRequiredError(AvitoBlockedError):
    """Avito requires a user to complete the visible confirmation challenge."""


class AvitoHardBlockedError(AvitoBlockedError):
    """Avito explicitly reports an IP block that must not use transient waiting."""


class AvitoParseError(AvitoError):
    """The response did not contain a supported search result format."""


class _AvitoProxyRotationRequired(AvitoBlockedError):
    """Internal signal indicating that the current Avito route should be replaced."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_path: Path | None = None,
        notification_error: AvitoBlockedError | None = None,
        replace_identity: bool = True,
    ):
        super().__init__(message, diagnostic_path=diagnostic_path)
        self.notification_error = notification_error
        self.replace_identity = replace_identity


BlockedCallback = Callable[[AvitoBlockedError], Awaitable[None]]


_CITY_ALIASES = {
    "москва": "moskva",
    "санкт-петербург": "sankt-peterburg",
    "санкт петербург": "sankt-peterburg",
    "спб": "sankt-peterburg",
    "казань": "kazan",
    "екатеринбург": "ekaterinburg",
    "нижний новгород": "nizhniy_novgorod",
    "новосибирск": "novosibirsk",
    "ростов-на-дону": "rostov-na-donu",
    "самара": "samara",
    "омск": "omsk",
    "уфа": "ufa",
    "красноярск": "krasnoyarsk",
    "пермь": "perm",
    "воронеж": "voronezh",
    "волгоград": "volgograd",
    "краснодар": "krasnodar",
    "тюмень": "tyumen",
    "вся россия": "rossiya",
    "россия": "rossiya",
}

_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def city_slug(city: str) -> str:
    normalized = " ".join(city.strip().lower().split())
    if not normalized:
        raise ValueError("Город не может быть пустым")
    if normalized in _CITY_ALIASES:
        return _CITY_ALIASES[normalized]
    slug = normalized.translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    if not slug:
        raise ValueError("Не удалось преобразовать город в адрес Avito")
    return slug


def build_search_url(
    query: str,
    city: str,
    price_min: int | None = None,
    price_max: int | None = None,
) -> str:
    query = " ".join(query.split())
    if not query:
        raise ValueError("Поисковый запрос не может быть пустым")
    if price_min is not None and price_min < 0:
        raise ValueError("Минимальная цена не может быть отрицательной")
    if price_max is not None and price_max < 0:
        raise ValueError("Максимальная цена не может быть отрицательной")
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ValueError("Минимальная цена не может быть больше максимальной")

    params: dict[str, str | int] = {"q": query, "s": 104}
    if price_min is not None:
        params["pmin"] = price_min
    if price_max is not None:
        params["pmax"] = price_max
    return f"{AVITO_BASE_URL}/{city_slug(city)}?{urlencode(params)}"


def _price_from_text(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _item_id(url: str, fallback: str | None = None) -> str | None:
    if fallback and fallback.strip():
        return fallback.strip()
    path = urlparse(url).path.rstrip("/")
    match = re.search(r"_(\d{6,})$", path)
    return match.group(1) if match else None


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    value = " ".join(node.get_text(" ", strip=True).split())
    return value or None


def _first(card: Tag, selectors: Iterable[str]) -> Tag | None:
    for selector in selectors:
        node = card.select_one(selector)
        if node is not None:
            return node
    return None


def _parse_cards(soup: BeautifulSoup) -> list[AvitoItem]:
    cards = soup.select('[data-marker="item"], [data-item-id][itemtype*="Product"]')
    result: dict[str, AvitoItem] = {}
    for card in cards:
        if not isinstance(card, Tag):
            continue
        link = _first(
            card,
            (
                'a[data-marker="item-title"]',
                'a[itemprop="url"]',
                'a[href*="_"]',
            ),
        )
        href = link.get("href") if link else None
        if not isinstance(href, str) or not href:
            continue
        url = urljoin(AVITO_BASE_URL, href)
        item_id = _item_id(url, card.get("data-item-id"))
        if not item_id:
            continue

        title_node = _first(card, ('[data-marker="item-title"]', '[itemprop="name"]', "h3"))
        title = _text(title_node) or (link.get("title") if link else None)
        if not isinstance(title, str) or not title.strip():
            continue

        price_meta = card.select_one('[itemprop="price"][content]')
        if price_meta and isinstance(price_meta.get("content"), str):
            price = _price_from_text(price_meta.get("content"))
        else:
            price = _price_from_text(
                _text(_first(card, ('[data-marker="item-price"]', '[class*="price"]')))
            )

        location = _text(
            _first(card, ('[data-marker="item-address"]', '[class*="geo"]', '[class*="address"]'))
        )
        image = _first(card, ('img[itemprop="image"]', "img"))
        image_url = None
        if image:
            for attr in ("src", "data-src"):
                raw = image.get(attr)
                if isinstance(raw, str) and raw.startswith(("http://", "https://")):
                    image_url = raw
                    break

        result[item_id] = AvitoItem(
            id=item_id,
            title=title.strip(),
            price=price,
            url=url,
            location=location,
            image_url=image_url,
        )
    return list(result.values())


def _json_products(value: object) -> Iterable[dict[str, object]]:
    if isinstance(value, dict):
        kind = value.get("@type")
        if kind == "Product" or ("name" in value and ("url" in value or "urlPath" in value)):
            yield value
        for child in value.values():
            yield from _json_products(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_products(child)


def _parse_json_ld(soup: BeautifulSoup) -> list[AvitoItem]:
    result: dict[str, AvitoItem] = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text(strip=True))
        except (json.JSONDecodeError, TypeError):
            continue
        for product in _json_products(payload):
            raw_url = product.get("url") or product.get("urlPath")
            title = product.get("name") or product.get("title")
            if not isinstance(raw_url, str) or not isinstance(title, str):
                continue
            url = urljoin(AVITO_BASE_URL, raw_url)
            item_id = _item_id(url, str(product.get("sku") or product.get("productID") or ""))
            if not item_id:
                continue
            offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
            price = _price_from_text(str(offers.get("price") or product.get("price") or ""))
            image = product.get("image")
            image_url = image if isinstance(image, str) else None
            result[item_id] = AvitoItem(item_id, title.strip(), price, url, image_url=image_url)
    return list(result.values())


def parse_search_html(html: str) -> list[AvitoItem]:
    page_state = extract_page_state(html)
    if page_state is not None and page_state.items:
        return list(page_state.items)

    soup = BeautifulSoup(html, "html.parser")
    items = _parse_cards(soup) or _parse_json_ld(soup)
    if items:
        return items

    # A real SERP is stronger evidence than text left in hidden/template nodes.
    # If no structured result was found, the block marker remains authoritative.
    if _is_blocked_html(html):
        raise AvitoBlockedError("Avito ограничил доступ с текущего IP или запросил капчу")

    if page_state is not None and page_state.catalog_item_count:
        raise AvitoParseError(
            "Avito вернул элементы catalog в неподдерживаемом формате"
        )

    page_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    empty_markers = ("ничего не найдено", "объявлений не найдено", "нет подходящих объявлений")
    if any(marker in page_text for marker in empty_markers):
        return []
    raise AvitoParseError("Avito ответил в неизвестном формате: карточки объявлений не найдены")


class _AvitoProxyPool:
    def __init__(self, settings: Settings):
        self._mode = settings.avito_proxy_mode
        self._proxies = settings.avito_proxy_pool
        self._index = (
            random.randrange(len(self._proxies))
            if self._mode == "proxy" and self._proxies
            else -1
        )

    @property
    def current(self) -> str | None:
        if self._index < 0 or not self._proxies:
            return None
        return self._proxies[self._index]

    def rotate(self) -> str | None:
        if not self._proxies or self._mode == "direct":
            return None
        if self._index < 0:
            self._index = 0
        elif len(self._proxies) > 1:
            self._index = (self._index + 1) % len(self._proxies)
        return self.current

    def use_direct(self) -> None:
        if self._mode == "fallback":
            self._index = -1

    def select(self, predicate: Callable[[str], bool]) -> str | None:
        """Select the first pool route accepted by predicate, without network I/O."""
        if not self._proxies or self._mode == "direct":
            return None
        start = self._index if self._index >= 0 else 0
        for offset in range(len(self._proxies)):
            index = (start + offset) % len(self._proxies)
            candidate = self._proxies[index]
            if predicate(candidate):
                self._index = index
                return candidate
        return None


class _RouteHealthStore:
    """Persist request budgets and quarantine state for each real egress route."""

    def __init__(self, path: Path, *, window_seconds: int, max_requests: int) -> None:
        self.path = path
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._state = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): value
            for key, value in payload.items()
            if isinstance(value, dict)
        }

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            logger.warning("Не удалось сохранить состояние маршрутов Avito: %s", exc)

    def _entry(self, key: str) -> dict[str, Any]:
        return self._state.setdefault(key, {})

    def quarantine_remaining(self, key: str, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        raw = self._entry(key).get("quarantined_until", 0)
        try:
            remaining = float(raw) - current
        except (TypeError, ValueError):
            return 0
        return max(0, math.ceil(remaining))

    def request_budget_remaining(self, key: str, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        entry = self._entry(key)
        raw_requests = entry.get("requests", [])
        requests = [
            float(value)
            for value in raw_requests
            if isinstance(value, (int, float)) and current - float(value) < 3600
        ]
        entry["requests"] = requests
        window = [stamp for stamp in requests if current - stamp < self.window_seconds]
        if len(window) < self.max_requests:
            return 0
        return max(1, math.ceil(window[0] + self.window_seconds - current))

    def record_request(self, key: str, *, now: float | None = None) -> None:
        current = time.time() if now is None else now
        entry = self._entry(key)
        requests = entry.setdefault("requests", [])
        if not isinstance(requests, list):
            requests = []
        requests = [
            float(value)
            for value in requests
            if isinstance(value, (int, float)) and current - float(value) < 3600
        ]
        requests.append(current)
        entry["requests"] = requests
        self._save()

    def quarantine(self, key: str, seconds: int, reason: str) -> None:
        entry = self._entry(key)
        entry["quarantined_until"] = max(
            float(entry.get("quarantined_until", 0) or 0),
            time.time() + seconds,
        )
        entry["last_failure_at"] = time.time()
        entry["last_failure_reason"] = reason
        failures = entry.setdefault("failures", {})
        if not isinstance(failures, dict):
            failures = {}
        failures[reason] = int(failures.get(reason, 0) or 0) + 1
        entry["failures"] = failures
        self._save()

    def record_success(self, key: str) -> None:
        entry = self._entry(key)
        entry["last_success_at"] = time.time()
        self._save()

    def public_ip_for_route(self, route_id: str) -> str | None:
        value = self._entry(f"route:{route_id}").get("public_ip")
        if not isinstance(value, str):
            return None
        try:
            return str(ip_address(value))
        except ValueError:
            return None

    def associate_public_ip(self, route_id: str, public_ip: str) -> None:
        self._entry(f"route:{route_id}")["public_ip"] = public_ip
        self._save()


def _proxy_label(proxy_url: str | None) -> str:
    if not proxy_url:
        return "direct"
    parsed = urlsplit(proxy_url)
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


def _proxy_route_id(proxy_url: str | None) -> str:
    """Return a credential-aware opaque route id without exposing proxy secrets."""
    if not proxy_url:
        return "direct"
    return hashlib.sha256(proxy_url.encode("utf-8")).hexdigest()[:16]


def _playwright_proxy(proxy_url: str) -> dict[str, str]:
    parsed = urlsplit(proxy_url)
    assert parsed.hostname is not None and parsed.port is not None
    result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username is not None:
        result["username"] = unquote(parsed.username)
    if parsed.password is not None:
        result["password"] = unquote(parsed.password)
    return result


def _is_browser_closed_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return exc.__class__.__name__ == "TargetClosedError" or (
        "target page, context or browser has been closed" in text
        or "browsercontext.new_page: target" in text and "closed" in text
    )


class AvitoClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._avito_proxies = _AvitoProxyPool(settings)
        self._direct_session: aiohttp.ClientSession | None = None
        self._proxy_session: aiohttp.ClientSession | None = None
        self._curl_session: CurlAsyncSession | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_context: BrowserContext | None = None
        self._browser_session: BrowserSession | None = None
        self._browser_identity: BrowserIdentity | None = None
        self._browser_launches = 0
        self._browser_sessions_started = 0
        self._identity_prepared_for_browser_start = False
        self._proxy_prepared_for_browser_start = False
        self._browser_lock = asyncio.Lock()
        self._request_limiter_lock = asyncio.Lock()
        self._browser_warmed_up = False
        self._last_avito_request_at: float | None = None
        self._cooldown_until: float | None = None
        self._route_public_ips: dict[str, str] = {}
        health_path = settings.database_path.parent / "avito-route-health.json"
        self._route_health = _RouteHealthStore(
            health_path,
            window_seconds=settings.avito_request_window_seconds,
            max_requests=settings.avito_max_requests_per_window,
        )
        self.last_route: str | None = None

    def _route_health_key(
        self,
        proxy_url: str | None = None,
        *,
        use_current_route: bool = True,
    ) -> str:
        selected = self._avito_proxies.current if use_current_route else proxy_url
        route_id = _proxy_route_id(selected)
        public_ip = self._route_public_ips.get(
            route_id
        ) or self._route_health.public_ip_for_route(route_id)
        return f"ip:{public_ip}" if public_ip else f"route:{route_id}"

    async def _before_avito_request(
        self,
        *,
        explicit_delay_applied: bool = False,
        route_key: str | None = None,
    ) -> None:
        async with self._request_limiter_lock:
            key = route_key or self._route_health_key()
            quarantine = self._route_health.quarantine_remaining(key)
            if quarantine:
                raise AvitoRateLimitedError(
                    f"Маршрут Avito находится в карантине ещё {quarantine} секунд",
                    retry_after_seconds=quarantine,
                )

            budget_wait = self._route_health.request_budget_remaining(key)
            if budget_wait:
                logger.warning(
                    "Локальный лимит запросов Avito для %s исчерпан; пауза %s с",
                    key,
                    budget_wait,
                )
                await asyncio.sleep(budget_wait)

            loop = asyncio.get_running_loop()
            if self._last_avito_request_at is not None and not explicit_delay_applied:
                minimum = self._settings.avito_min_request_interval_seconds
                jitter = random.uniform(0, self._settings.avito_request_jitter_seconds)
                remaining = minimum + jitter - (loop.time() - self._last_avito_request_at)
                if remaining > 0:
                    logger.info("Пауза %.1f с перед следующим запросом Avito", remaining)
                    await asyncio.sleep(remaining)
            self._last_avito_request_at = loop.time()
            self._route_health.record_request(key)

    def _record_route_success(self, route_key: str | None = None) -> None:
        self._route_health.record_success(route_key or self._route_health_key())

    def _quarantine_current_route(
        self,
        *,
        seconds: int,
        reason: str,
        route_key: str | None = None,
    ) -> None:
        self._route_health.quarantine(
            route_key or self._route_health_key(), seconds, reason
        )

    def _rate_limit_error(
        self,
        headers: Mapping[str, object] | None = None,
        *,
        message: str = "Avito ограничил частоту запросов (HTTP 429)",
        route_key: str | None = None,
    ) -> AvitoRateLimitedError:
        retry_after = _retry_after_seconds(headers)
        retry_after = retry_after or self._settings.avito_rate_limit_cooldown_seconds
        self._quarantine_current_route(
            seconds=retry_after,
            reason="http-429",
            route_key=route_key,
        )
        return AvitoRateLimitedError(message, retry_after_seconds=retry_after)

    def _ensure_browser_identity(self) -> BrowserIdentity:
        if self._browser_identity is None:
            impersonate = resolve_http_impersonate(
                self._settings.user_agent,
                self._settings.avito_http_impersonate,
            )
            self._browser_identity = load_browser_identity(
                profile_path=self._settings.avito_browser_profile_path,
                user_agent=self._settings.user_agent,
                impersonate=impersonate,
                locale=self._settings.avito_browser_locale,
                timezone_id=self._settings.avito_browser_timezone,
            )
        return self._browser_identity

    def _generate_next_browser_identity(self) -> BrowserIdentity:
        previous = self._browser_identity
        if previous is None:
            return self._ensure_browser_identity()
        self._browser_identity = generate_browser_identity(
            user_agent=previous.user_agent,
            impersonate=previous.impersonate,
            locale=previous.locale,
            timezone_id=previous.timezone_id,
            previous=previous,
        )
        save_browser_identity(
            self._settings.avito_browser_profile_path,
            self._browser_identity,
        )
        return self._browser_identity

    async def _prepare_browser_start(self) -> BrowserIdentity:
        mode = self._settings.avito_proxy_mode
        route_refreshed_by_provider = bool(
            self._proxy_prepared_for_browser_start
            and self._settings.avito_proxy_change_url
        )
        if (
            mode == "proxy"
            and self._avito_proxies.current
            and not route_refreshed_by_provider
        ):
            selected = self._avito_proxies.select(
                lambda proxy: self._route_health.quarantine_remaining(
                    self._route_health_key(proxy, use_current_route=False)
                )
                == 0
            )
            if selected is None:
                waits = [
                    self._route_health.quarantine_remaining(
                        self._route_health_key(proxy, use_current_route=False)
                    )
                    for proxy in self._settings.avito_proxy_pool
                ]
                remaining = min((wait for wait in waits if wait > 0), default=1)
                raise AvitoRateLimitedError(
                    "Все настроенные маршруты Avito находятся в карантине",
                    retry_after_seconds=max(1, remaining),
                )
        elif mode == "fallback" and not route_refreshed_by_provider:
            current_proxy = self._avito_proxies.current
            current_key = self._route_health_key(
                current_proxy,
                use_current_route=False,
            )
            if self._route_health.quarantine_remaining(current_key):
                previous_route = _proxy_label(current_proxy)
                switched = False
                direct_key = self._route_health_key(None, use_current_route=False)
                if (
                    current_proxy is not None
                    and self._route_health.quarantine_remaining(direct_key) == 0
                ):
                    self._avito_proxies.use_direct()
                    switched = True
                else:
                    selected = self._avito_proxies.select(
                        lambda proxy: self._route_health.quarantine_remaining(
                            self._route_health_key(proxy, use_current_route=False)
                        )
                        == 0
                    )
                    switched = selected is not None
                if not switched:
                    candidates: tuple[str | None, ...] = (
                        None,
                        *self._settings.avito_proxy_pool,
                    )
                    waits = [
                        self._route_health.quarantine_remaining(
                            self._route_health_key(
                                proxy,
                                use_current_route=False,
                            )
                        )
                        for proxy in candidates
                    ]
                    remaining = min((wait for wait in waits if wait > 0), default=1)
                    raise AvitoRateLimitedError(
                        "Все direct/fallback-маршруты Avito находятся в карантине",
                        retry_after_seconds=max(1, remaining),
                    )
                logger.info(
                    "Avito: карантин маршрута %s ещё активен; старт через %s",
                    previous_route,
                    _proxy_label(self._avito_proxies.current),
                )
        if self._browser_launches > 0:
            if (
                self._settings.avito_identity_rotate_on_browser_start
                and not self._identity_prepared_for_browser_start
            ):
                self._generate_next_browser_identity()
            if (
                self._settings.avito_proxy_rotate_on_browser_start
                and self._proxy_rotation_available()
                and not self._proxy_prepared_for_browser_start
            ):
                previous_route = _proxy_label(self._avito_proxies.current)
                await self._call_proxy_change_url()
                next_proxy = self._select_next_healthy_route(
                    self._avito_proxies.current
                )
                delay = self._settings.avito_proxy_rotation_delay_seconds
                logger.info(
                    "Новый маршрут для перезапуска Chromium: %s -> %s; ожидание %s с",
                    previous_route,
                    _proxy_label(next_proxy),
                    delay,
                )
                if delay:
                    await asyncio.sleep(delay)
        self._identity_prepared_for_browser_start = False
        self._proxy_prepared_for_browser_start = False
        return self._ensure_browser_identity()

    async def _prepare_new_user_session(self) -> None:
        if (
            not self._settings.avito_new_user_per_session
            or self._browser_sessions_started == 0
        ):
            return
        logger.info(
            "Подготовка нового пользователя Chromium: предыдущих сессий=%s",
            self._browser_sessions_started,
        )
        await self._close_browser_network()

    async def __aenter__(self) -> AvitoClient:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._settings.avito_transport in {"browser", "hybrid"}:
            await self._start_browser()
        else:
            await self._get_session(use_proxy=self._routes()[0])

    async def close(self) -> None:
        for session in (self._direct_session, self._proxy_session):
            if session and not session.closed:
                await session.close()
        if self._curl_session is not None:
            await self._curl_session.close()
            self._curl_session = None
        if self._browser_context is not None:
            await self._browser_context.close()
            self._browser_context = None
            self._browser_session = None
            self._browser_warmed_up = False
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _start_browser(self) -> None:
        if self._browser is not None:
            return

        identity = await self._prepare_browser_start()
        executable_path = resolve_chromium_executable(self._settings)
        proxy_url = self._avito_proxies.current
        browser_args = [
            "--disable-dev-shm-usage",
            f"--window-size={identity.screen_width},{identity.screen_height}",
        ]
        if self._settings.avito_browser_stealth:
            browser_args.append("--disable-blink-features=AutomationControlled")
        if proxy_url is None:
            browser_args.insert(0, "--no-proxy-server")
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        playwright = self._playwright
        try:
            browser = await playwright.chromium.launch(
                executable_path=executable_path,
                headless=self._settings.avito_browser_headless,
                args=browser_args,
            )
        except PlaywrightError as exc:
            await playwright.stop()
            if self._playwright is playwright:
                self._playwright = None
            executable_hint = executable_path or "встроенный Chromium Playwright"
            raise AvitoNetworkError(
                f"Не удалось запустить Chromium ({executable_hint}): {exc}"
            ) from exc
        self._browser = browser
        self._browser_launches += 1
        browser.on("disconnected", lambda *_args: self._mark_browser_closed(browser))

        logger.info(
            "Chromium для Avito запущен: route=%s, executable=%s, headless=%s, "
            "session_mode=isolated, identity=%s, viewport=%sx%s, impersonate=%s",
            _proxy_label(proxy_url),
            executable_path or "playwright",
            self._settings.avito_browser_headless,
            identity.identity_id,
            identity.viewport_width,
            identity.viewport_height,
            identity.impersonate,
        )
        await self._log_browser_public_ip(proxy_url)

    async def _start_browser_session(self) -> None:
        if self._browser_context is not None:
            return
        assert self._browser is not None
        proxy_url = self._avito_proxies.current
        manager = BrowserIdentityManager(
            self._browser,
            proxy=_playwright_proxy(proxy_url) if proxy_url else None,
            stealth=self._settings.avito_browser_stealth,
        )
        storage_state = self._browser_storage_state_path()
        try:
            maintain_browser_storage_directory(
                storage_state.parent,
                preserve=(storage_state,),
            )
        except OSError as exc:
            logger.warning(
                "Не удалось подготовить приватное хранилище Chromium: %s",
                exc,
            )
        stored_state = (
            storage_state
            if not self._settings.avito_new_user_per_session
            and storage_state.is_file()
            and not storage_state.is_symlink()
            else None
        )
        try:
            session = await manager.create_session(
                self._ensure_browser_identity(),
                storage_state=stored_state,
            )
        except PlaywrightError:
            if stored_state is None:
                raise
            # A truncated or schema-incompatible Playwright storage file must not
            # trap every future check in the same startup failure.  Retry once
            # without it, but preserve a valid state if Chromium itself is broken.
            logger.warning(
                "Saved Chromium storage state was rejected; testing a clean "
                "route-bound session: %s",
                stored_state,
            )
            session = await manager.create_session(
                self._ensure_browser_identity(),
                storage_state=None,
            )
            with suppress(OSError):
                stored_state.unlink()
        self._browser_sessions_started += 1
        self._browser_session = session
        self._browser_context = session.context
        session.context.on(
            "close",
            lambda *_args: self._mark_browser_context_closed(session.context),
        )
        self._browser_warmed_up = False

    def _browser_storage_state_path(
        self,
        *,
        identity_id: str | None = None,
        proxy_url: str | None = None,
    ) -> Path:
        identity = identity_id or self._ensure_browser_identity().identity_id
        route_id = _proxy_route_id(
            self._avito_proxies.current if proxy_url is None else proxy_url
        )
        return (
            self._settings.avito_browser_profile_path
            / "storage"
            / f"{route_id}-{identity}.json"
        )

    async def _save_browser_storage_state(self) -> None:
        context = self._browser_context
        if context is None or self._settings.avito_new_user_per_session:
            return
        target = self._browser_storage_state_path()
        temporary = target.with_suffix(".tmp")
        try:
            maintain_browser_storage_directory(
                target.parent,
                preserve=(target,),
            )
            with suppress(OSError):
                temporary.unlink()
            temporary.touch(mode=PRIVATE_FILE_MODE)
            harden_file_permissions(temporary)
            # Playwright omits IndexedDB unless explicitly requested.  Persist it
            # together with cookies/localStorage so a healthy route does not become
            # a partially new session after an ordinary process restart.
            try:
                await context.storage_state(path=str(temporary), indexed_db=True)
            except TypeError:
                # Playwright <1.51 did not expose indexed_db.  Keep cookies and
                # localStorage persistence instead of losing all healthy state.
                await context.storage_state(path=str(temporary))
            harden_file_permissions(temporary)
            temporary.replace(target)
            harden_file_permissions(target)
            maintain_browser_storage_directory(
                target.parent,
                preserve=(target,),
            )
        except (OSError, PlaywrightError) as exc:
            with suppress(OSError):
                temporary.unlink()
            logger.warning("Не удалось сохранить storage state Chromium: %s", exc)

    def _discard_browser_storage_state(self, identity_id: str) -> None:
        target = self._browser_storage_state_path(identity_id=identity_id)
        with suppress(OSError):
            target.unlink()

    async def _close_browser_session(self) -> None:
        context = self._browser_context
        session = self._browser_session
        self._browser_context = None
        self._browser_session = None
        self._browser_warmed_up = False
        if context is not None:
            close = getattr(context, "close", None)
            if close is not None:
                with suppress(PlaywrightError):
                    await close()
        if session is not None:
            logger.info("Изолированная Chromium-сессия закрыта: session=%s", session.session_id)

    def _mark_browser_closed(self, browser: Browser) -> None:
        if self._browser is browser:
            self._browser = None
            self._browser_context = None
            self._browser_session = None
            self._browser_warmed_up = False

    def _mark_browser_context_closed(self, browser_context: BrowserContext) -> None:
        if self._browser_context is browser_context:
            self._browser_context = None
            self._browser_warmed_up = False

    async def _reset_closed_browser(self) -> None:
        self._browser = None
        self._browser_context = None
        self._browser_session = None
        self._browser_warmed_up = False
        if self._curl_session is not None:
            await self._curl_session.close()
            self._curl_session = None

    async def _log_browser_public_ip(self, proxy_url: str | None) -> None:
        if not self._settings.avito_log_public_ip or self._playwright is None:
            return

        request_context = None
        route = _proxy_label(proxy_url)
        route_id = _proxy_route_id(proxy_url)
        try:
            request_context = await self._playwright.request.new_context(
                proxy=_playwright_proxy(proxy_url) if proxy_url else None,
            )
            response = await request_context.get(
                PUBLIC_IP_CHECK_URL,
                timeout=min(8_000, self._settings.request_timeout_seconds * 1000),
            )
            if not response.ok:
                logger.warning(
                    "Не удалось определить выходной IP Chromium: route=%s, HTTP %s",
                    route,
                    response.status,
                )
                return
            payload = await response.json()
            raw_ip = payload.get("ip") if isinstance(payload, dict) else None
            if not isinstance(raw_ip, str):
                raise ValueError("ответ не содержит поле ip")
            public_ip = str(ip_address(raw_ip.strip()))
            self._route_public_ips[route_id] = public_ip
            self._route_health.associate_public_ip(route_id, public_ip)
            logger.info(
                "Выходной IP Chromium для Avito: %s, route=%s",
                public_ip,
                route,
            )
        except (PlaywrightError, ValueError, TypeError) as exc:
            logger.warning(
                "Не удалось определить выходной IP Chromium: route=%s, ошибка=%s",
                route,
                type(exc).__name__,
            )
        finally:
            if request_context is not None:
                with suppress(PlaywrightError):
                    await request_context.dispose()

    def _routes(self) -> tuple[bool, ...]:
        mode = self._settings.avito_proxy_mode
        has_proxy = bool(
            self._settings.avito_proxy_pool or self._settings.http_proxy
        )
        if mode == "proxy":
            return (True,)
        if mode == "fallback" and has_proxy:
            return (False, True)
        return (False,)

    async def _get_session(self, *, use_proxy: bool) -> tuple[aiohttp.ClientSession, str | None]:
        timeout = aiohttp.ClientTimeout(total=self._settings.request_timeout_seconds)
        if not use_proxy:
            if self._direct_session is None or self._direct_session.closed:
                self._direct_session = aiohttp.ClientSession(
                    timeout=timeout, raise_for_status=False
                )
            return self._direct_session, None

        proxy_url = self._avito_proxies.current
        if proxy_url is None and self._settings.avito_proxy_pool:
            proxy_url = self._settings.avito_proxy_pool[0]
        if proxy_url is None:
            proxy_url = self._settings.http_proxy
        if not proxy_url:
            raise AvitoNetworkError("Для прокси-маршрута не задан AVITO_PROXY")
        scheme = urlsplit(proxy_url).scheme.lower()
        if scheme in {"socks4", "socks5"}:
            if self._proxy_session is None or self._proxy_session.closed:
                connector = ProxyConnector.from_url(
                    proxy_url,
                    rdns=self._settings.avito_proxy_rdns,
                )
                self._proxy_session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    raise_for_status=False,
                )
            return self._proxy_session, None

        if self._proxy_session is None or self._proxy_session.closed:
            self._proxy_session = aiohttp.ClientSession(timeout=timeout, raise_for_status=False)
        return self._proxy_session, proxy_url

    async def search(
        self,
        url: str,
        *,
        on_blocked: BlockedCallback | None = None,
        initial: bool = False,
    ) -> list[AvitoItem]:
        if self._settings.avito_transport in {"browser", "hybrid"}:
            route_kind = "proxy" if self._avito_proxies.current else "direct"
            self.last_route = (
                f"chromium+curl-{route_kind}"
                if self._settings.avito_transport == "hybrid"
                else f"chromium-{route_kind}"
            )
            return await self._search_browser(url, on_blocked=on_blocked, initial=initial)

        headers = {
            "User-Agent": self._settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Cache-Control": "no-cache",
        }
        if self._settings.avito_cookie:
            headers["Cookie"] = self._settings.avito_cookie

        route_errors: list[str] = []
        was_blocked = False
        routes = self._routes()
        for index, use_proxy in enumerate(routes):
            route_name = "proxy" if use_proxy else "direct"
            self.last_route = route_name
            try:
                return await self._search_route(url, headers, use_proxy=use_proxy)
            except AvitoError as exc:
                if isinstance(exc, (AvitoRateLimitedError, AvitoSessionError)):
                    raise
                route_errors.append(f"{route_name}: {exc}")
                was_blocked = was_blocked or isinstance(exc, AvitoBlockedError)
                if index + 1 < len(routes):
                    logger.warning(
                        "Маршрут Avito %s не сработал (%s); переключаюсь на прокси",
                        route_name,
                        exc,
                    )
                    continue
                if len(route_errors) == 1:
                    raise
        combined_error = "; ".join(route_errors)
        if was_blocked:
            raise AvitoBlockedError(combined_error)
        raise AvitoNetworkError(combined_error)

    async def _search_browser(
        self,
        url: str,
        *,
        on_blocked: BlockedCallback | None = None,
        initial: bool = False,
    ) -> list[AvitoItem]:
        async with self._browser_lock:
            self._raise_if_cooling_down()
            await self._prepare_new_user_session()
            rotations = 0
            browser_restarts = 0
            while True:
                await self._start_browser()
                route_quarantine = self._route_health.quarantine_remaining(
                    self._route_health_key()
                )
                if route_quarantine:
                    logger.warning(
                        "Выходной IP маршрута %s уже в карантине ещё %s с",
                        _proxy_label(self._avito_proxies.current),
                        route_quarantine,
                    )
                    if (
                        self._proxy_rotation_available()
                        and rotations < self._settings.avito_proxy_max_rotations
                    ):
                        rotations += 1
                        await self._rotate_avito_proxy(rotations)
                        continue
                    await self._close_browser_network()
                    raise AvitoRateLimitedError(
                        "Выбранный proxy endpoint выходит через уже "
                        "заблокированный public IP",
                        retry_after_seconds=route_quarantine,
                    )
                route_kind = "proxy" if self._avito_proxies.current else "direct"
                self.last_route = (
                    f"chromium+curl-{route_kind}"
                    if self._settings.avito_transport == "hybrid"
                    else f"chromium-{route_kind}"
                )
                await self._start_browser_session()
                try:
                    return await self._search_browser_with_current_proxy(
                        url,
                        on_blocked=on_blocked,
                        initial=initial,
                    )
                except _AvitoProxyRotationRequired as exc:
                    if (
                        not self._proxy_rotation_available()
                        or rotations >= self._settings.avito_proxy_max_rotations
                    ):
                        await self._replace_blocked_browser_identity(
                            "исчерпан лимит смен IP"
                        )
                        self._start_cooldown()
                        cooldown = self._settings.avito_cooldown_seconds
                        raise AvitoBlockedError(
                            f"Avito не открылся после {rotations} смен IP: {exc}; "
                            f"парсер приостановлен на {max(1, cooldown // 3600)} ч.",
                            diagnostic_path=exc.diagnostic_path,
                            retry_after_seconds=cooldown,
                        ) from exc
                    rotations += 1
                    await self._rotate_avito_proxy(
                        rotations,
                        replace_identity=exc.replace_identity,
                    )
                    if exc.notification_error is not None and on_blocked is not None:
                        try:
                            await on_blocked(exc.notification_error)
                        except Exception:
                            logger.exception(
                                "Не удалось отправить уведомление о блокировке Avito"
                            )
                except AvitoNetworkError:
                    failed_route = self._route_health_key()
                    self._route_health.quarantine(
                        failed_route,
                        self._settings.avito_proxy_network_failure_cooldown_seconds,
                        "network-failure",
                    )
                    if (
                        not self._proxy_rotation_available()
                        or rotations >= self._settings.avito_proxy_max_rotations
                    ):
                        raise
                    rotations += 1
                    logger.warning(
                        "Маршрут %s временно исключён после сетевой ошибки; "
                        "переключаюсь на следующий доступный маршрут",
                        _proxy_label(self._avito_proxies.current),
                    )
                    await self._rotate_avito_proxy(
                        rotations,
                        replace_identity=False,
                    )
                except PlaywrightError as exc:
                    if not _is_browser_closed_error(exc):
                        raise AvitoNetworkError(
                            f"Ошибка управления Chromium: {type(exc).__name__}"
                        ) from exc
                    if browser_restarts >= 1:
                        raise AvitoNetworkError(
                            "Chromium повторно закрылся во время проверки Avito"
                        ) from exc
                    browser_restarts += 1
                    logger.warning(
                        "Окно Chromium было закрыто; автоматически запускаю его заново"
                    )
                    await self._reset_closed_browser()
                finally:
                    if self._settings.avito_new_user_per_session:
                        await self._close_browser_session()

    async def _acquire_browser_page(self) -> Page:
        """Keep one working tab alive and reuse it between scheduled checks."""
        assert self._browser_context is not None
        active_pages = [
            page for page in self._browser_context.pages if not page.is_closed()
        ]
        blank_pages = [
            page for page in active_pages if page.url in {"", "about:blank"}
        ]
        if blank_pages:
            page = blank_pages[0]
            for duplicate in blank_pages[1:]:
                await duplicate.close()
            return page
        avito_pages = [page for page in active_pages if _is_avito_url(page.url)]
        if avito_pages:
            return avito_pages[0]
        if active_pages:
            return active_pages[0]
        return await self._browser_context.new_page()

    async def _search_browser_with_current_proxy(
        self,
        url: str,
        *,
        on_blocked: BlockedCallback | None = None,
        initial: bool = False,
    ) -> list[AvitoItem]:
        assert self._browser_context is not None
        last_error: Exception | None = None
        last_diagnostic_path: Path | None = None

        for attempt in range(1, self._settings.request_retries + 1):
            page = await self._acquire_browser_page()
            try:
                if not self._browser_warmed_up:
                    home_status, _, _ = await self._open_avito_home(
                        page,
                        on_blocked=on_blocked,
                    )
                    if home_status is not None and home_status >= 400:
                        raise AvitoNetworkError(
                            f"Главная страница Avito вернула HTTP {home_status}"
                        )
                    self._browser_warmed_up = True

                status, html, _ = await self._navigate_avito_page(
                    page,
                    url,
                    page_name="страница поиска",
                    referer=f"{AVITO_BASE_URL}/",
                    on_blocked=on_blocked,
                )
                if not _has_target_search_query(page.url, url):
                    diagnostic_path = await self._save_browser_diagnostic(page, status)
                    raise AvitoNetworkError(
                        "Avito перенаправил поиск на другую страницу; "
                        f"ожидался запрос q={parse_qs(urlsplit(url).query).get('q')}, "
                        f"получен URL {page.url}. Повторный переход не выполнялся, "
                        "чтобы не увеличивать нагрузку",
                        diagnostic_path=diagnostic_path,
                    )
                if status in AVITO_BLOCK_HTTP_STATUSES:
                    if status == 429:
                        raise self._rate_limit_error(
                            message="Chromium получил от Avito HTTP 429"
                        )
                    raise AvitoBlockedError(f"Chromium получил от Avito HTTP {status}")
                if status == 401:
                    raise AvitoSessionError("Chromium получил от Avito HTTP 401")
                if status is not None and status >= 500:
                    raise AvitoNetworkError(f"Chromium получил от Avito HTTP {status}")
                if status is not None and status >= 400:
                    raise AvitoNetworkError(f"Неожиданный HTTP-статус Avito: {status}")

                page_state = extract_page_state(html)
                if page_state is None or not page_state.items:
                    with suppress(PlaywrightTimeoutError):
                        await page.wait_for_function(
                            AVITO_SEARCH_TERMINAL_SCRIPT,
                            timeout=self._settings.request_timeout_seconds * 1000,
                        )
                html = await page.content()
                status, html, _ = await self._wait_then_reload_avito_page(
                    page,
                    status=status,
                    html=html,
                    page_name=AVITO_SEARCH_PAGE_NAME,
                    on_blocked=on_blocked,
                    require_expected_dom=True,
                )
                if not _has_target_search_query(page.url, url):
                    diagnostic_path = await self._save_browser_diagnostic(page, status)
                    raise AvitoNetworkError(
                        "Avito изменил адрес поиска во время загрузки; "
                        f"получен URL {page.url}",
                        diagnostic_path=diagnostic_path,
                    )
                await self._save_browser_snapshot(page)
                try:
                    page_state = extract_page_state(html)
                    items = parse_search_html(html)
                    if self._settings.avito_transport == "hybrid" and page_state is not None:
                        items = await self._extend_with_api_pages(
                            items,
                            page_state=page_state,
                            search_url=url,
                            max_pages=(
                                self._settings.avito_initial_api_max_pages
                                if initial
                                else self._settings.avito_api_max_pages
                            ),
                        )
                    await self._save_browser_storage_state()
                    self._record_route_success()
                    return items[: self._settings.max_results]
                except (AvitoBlockedError, AvitoParseError) as exc:
                    exc.diagnostic_path = await self._save_browser_diagnostic(page, status)
                    raise
            except AvitoBlockedError:
                raise
            except (PlaywrightTimeoutError, PlaywrightError, AvitoNetworkError) as exc:
                if _is_browser_closed_error(exc):
                    raise
                last_error = exc
                if (
                    page.url in {"", "about:blank"}
                    and self._avito_proxies.current is not None
                    and self._proxy_rotation_available()
                ):
                    logger.warning(
                        "Прокси не смог открыть Avito: вкладка осталась about:blank; "
                        "переключаю IP без создания снимка. Ошибка: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
                    self._route_health.quarantine(
                        self._route_health_key(),
                        self._settings.avito_proxy_network_failure_cooldown_seconds,
                        "network-failure",
                    )
                    raise _AvitoProxyRotationRequired(
                        "Прокси не открыл Avito, вкладка осталась about:blank; "
                        "требуется сменить IP",
                        replace_identity=False,
                    ) from exc
                last_diagnostic_path = await self._save_browser_diagnostic(page, None)
                if attempt < self._settings.request_retries:
                    delay = min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning(
                        "Ошибка Chromium-запроса Avito, повтор через %.1f с: %s",
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
        raise AvitoNetworkError(
            f"Avito недоступен через Chromium: {last_error}",
            diagnostic_path=last_diagnostic_path,
        )

    async def _save_browser_snapshot(self, page: Page) -> Path | None:
        if not self._settings.avito_browser_snapshots or self._browser_session is None:
            return None
        session_id = self._browser_session.session_id
        target = (
            self._settings.database_path.parent
            / "diagnostics"
            / "browser-sessions"
            / f"{session_id}.json"
        )
        try:
            ensure_private_directory(target.parent.parent)
            ensure_private_directory(target.parent)
            snapshot = await collect_browser_snapshot(page)
            snapshot.update(
                {
                    "sessionId": session_id,
                    "identityId": self._browser_session.identity.identity_id,
                    "url": page.url,
                    "capturedAt": datetime.now().astimezone().isoformat(),
                }
            )
            save_browser_snapshot(snapshot, target)
            logger.info("Browser snapshot сохранён: session=%s path=%s", session_id, target)
            return target
        except (AttributeError, OSError, TypeError, PlaywrightError) as exc:
            logger.warning("Не удалось сохранить browser snapshot: %s", exc)
            return None

    def _proxy_rotation_available(self) -> bool:
        mode = self._settings.avito_proxy_mode
        if mode == "direct" or not self._settings.avito_proxy_rotation_enabled:
            return False
        if self._settings.avito_proxy_change_url:
            return True

        current_proxy = self._avito_proxies.current
        if mode == "fallback" and current_proxy is not None:
            direct_key = self._route_health_key(None, use_current_route=False)
            if self._route_health.quarantine_remaining(direct_key) == 0:
                return True
        return any(
            proxy != current_proxy
            and self._route_health.quarantine_remaining(
                self._route_health_key(proxy, use_current_route=False)
            )
            == 0
            for proxy in set(self._settings.avito_proxy_pool)
        )

    def proxy_rotation_available(self) -> bool:
        """Expose the current route capability for user-facing status messages."""
        return self._proxy_rotation_available()

    def _select_next_healthy_route(self, previous_proxy: str | None) -> str | None:
        """Select an actually different healthy route when one is available."""
        direct_key = self._route_health_key(None, use_current_route=False)
        if (
            self._settings.avito_proxy_mode == "fallback"
            and previous_proxy is not None
            and self._route_health.quarantine_remaining(direct_key) == 0
        ):
            self._avito_proxies.use_direct()
            return None

        selected = self._avito_proxies.select(
            lambda proxy: proxy != previous_proxy
            and self._route_health.quarantine_remaining(
                self._route_health_key(proxy, use_current_route=False)
            )
            == 0
        )
        if selected is not None:
            return selected

        # A provider change URL may replace the egress IP behind the same static
        # endpoint.  Public-IP verification after launch decides whether it is new.
        if self._settings.avito_proxy_change_url:
            return self._avito_proxies.rotate()
        return previous_proxy

    async def _replace_blocked_browser_identity(self, reason: str) -> None:
        previous = self._ensure_browser_identity()
        self._discard_browser_storage_state(previous.identity_id)
        context = self._browser_context
        if context is not None:
            for page in context.pages:
                if page.is_closed() or not _is_avito_url(page.url):
                    continue
                with suppress(PlaywrightError):
                    await page.evaluate(AVITO_SITE_DATA_CLEAR_SCRIPT)
            with suppress(PlaywrightError):
                await context.clear_cookies()
        if self._curl_session is not None:
            self._curl_session.cookies.clear()

        if self._settings.avito_identity_rotate_on_block:
            self._generate_next_browser_identity()
            self._identity_prepared_for_browser_start = True
        await self._close_browser_network()
        current = self._ensure_browser_identity()
        logger.warning(
            "Личность Chromium %s после блокировки (%s): %s -> %s; "
            "cookies и хранилища Avito очищены",
            "заменена" if current.identity_id != previous.identity_id else "сохранена",
            reason,
            previous.identity_id,
            current.identity_id,
        )

    async def _close_browser_network(self) -> None:
        if self._proxy_session is not None and not self._proxy_session.closed:
            await self._proxy_session.close()
            self._proxy_session = None
        if self._curl_session is not None:
            await self._curl_session.close()
            self._curl_session = None
        if self._browser_context is not None:
            await self._browser_context.close()
            self._browser_context = None
            self._browser_session = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._browser_warmed_up = False

    async def _call_proxy_change_url(self) -> None:
        change_url = self._settings.avito_proxy_change_url
        if not change_url:
            return
        timeout = aiohttp.ClientTimeout(total=self._settings.request_timeout_seconds)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout, trust_env=False) as session,
                session.get(change_url, allow_redirects=False) as response,
            ):
                if not 200 <= response.status < 300:
                    raise AvitoNetworkError(
                        "Сервис смены IP вернул ошибку "
                        f"HTTP {response.status}"
                    )
        except aiohttp.ClientError as exc:
            raise AvitoNetworkError(
                f"Не удалось вызвать сервис смены IP: {type(exc).__name__}"
            ) from exc

    async def _rotate_avito_proxy(
        self,
        rotation_number: int,
        *,
        replace_identity: bool = True,
    ) -> None:
        previous_proxy = self._avito_proxies.current
        previous_route = _proxy_label(previous_proxy)
        if replace_identity:
            await self._replace_blocked_browser_identity("смена IP")
        else:
            await self._close_browser_network()
        await self._call_proxy_change_url()
        next_proxy = self._select_next_healthy_route(previous_proxy)
        self._proxy_prepared_for_browser_start = True
        delay = self._settings.avito_proxy_rotation_delay_seconds
        logger.warning(
            "Avito: смена IP %s/%s, маршрут %s -> %s; ожидание %s с",
            rotation_number,
            self._settings.avito_proxy_max_rotations,
            previous_route,
            _proxy_label(next_proxy),
            delay,
        )
        if delay:
            await asyncio.sleep(delay)
        # Spacing is route-specific here: the next request goes through a newly
        # selected/verified egress and must not inherit the old route's delay.
        self._last_avito_request_at = None
        route_kind = "proxy" if next_proxy else "direct"
        self.last_route = (
            f"chromium+curl-{route_kind}"
            if self._settings.avito_transport == "hybrid"
            else f"chromium-{route_kind}"
        )

    async def _get_curl_session(self) -> CurlAsyncSession:
        if self._curl_session is not None:
            return self._curl_session

        identity = self._ensure_browser_identity()
        proxies: dict[str, str] | None = None
        proxy_url = self._avito_proxies.current
        if proxy_url is not None:
            proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
        self._curl_session = CurlAsyncSession(
            impersonate=identity.impersonate,
            headers=identity.http_headers,
            timeout=self._settings.request_timeout_seconds,
            trust_env=False,
            proxies=proxies,
        )
        return self._curl_session

    async def _sync_browser_cookies_to_curl(self, session: CurlAsyncSession) -> None:
        assert self._browser_context is not None
        browser_cookies = await self._browser_context.cookies([AVITO_BASE_URL])
        session.cookies.clear()
        synchronized = 0
        for cookie in browser_cookies:
            expires_value = cookie.get("expires")
            if (
                isinstance(expires_value, (int, float))
                and expires_value > 0
                and expires_value <= time.time()
            ):
                continue
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain") or ".avito.ru",
                path=cookie.get("path") or "/",
                secure=bool(cookie.get("secure")),
            )
            synchronized += 1
        logger.info(
            "Cookies Chromium -> HTTP синхронизированы: %s, identity=%s",
            synchronized,
            self._ensure_browser_identity().identity_id,
        )

    async def _sync_curl_cookies_to_browser(self, session: CurlAsyncSession) -> None:
        if self._browser_context is None:
            return
        browser_cookies: list[dict[str, object]] = []
        now = time.time()
        for cookie in session.cookies.jar:
            domain = (cookie.domain or ".avito.ru").lower()
            hostname = domain.lstrip(".")
            if hostname != "avito.ru" and not hostname.endswith(".avito.ru"):
                continue
            if cookie.expires is not None and cookie.expires <= now:
                continue
            browser_cookie: dict[str, object] = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
                "secure": bool(cookie.secure),
                "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
            }
            if cookie.expires is not None and cookie.expires > 0:
                browser_cookie["expires"] = float(cookie.expires)
            browser_cookies.append(browser_cookie)
        if not browser_cookies:
            return
        try:
            await self._browser_context.add_cookies(browser_cookies)
        except PlaywrightError as exc:
            logger.warning("Не удалось вернуть обновлённые cookies в Chromium: %s", exc)
            return
        logger.info(
            "Cookies HTTP -> Chromium синхронизированы: %s, identity=%s",
            len(browser_cookies),
            self._ensure_browser_identity().identity_id,
        )

    async def _request_api_page(
        self,
        *,
        page_number: int,
        page_state: AvitoPageState,
        search_url: str,
    ) -> list[AvitoItem]:
        session = await self._get_curl_session()
        params = dict(page_state.api_params)
        params.update(
            {
                "p": str(page_number),
                "context": page_state.context or "",
                "updateListOnly": "true",
            }
        )
        last_error: Exception | None = None
        for attempt in range(1, self._settings.request_retries + 1):
            try:
                await self._before_avito_request()
                response = await session.get(
                    f"{AVITO_BASE_URL}/web/1/js/items",
                    params=params,
                    headers={
                        "accept": "application/json, text/plain, */*",
                        "accept-language": "ru-RU,ru;q=0.9",
                        "referer": search_url,
                    },
                    allow_redirects=True,
                )
                if response.status_code == 429:
                    retry_after = (
                        _retry_after_seconds(response.headers)
                        or self._settings.avito_rate_limit_cooldown_seconds
                    )
                    raise AvitoRateLimitedError(
                        "JSON-пагинация Avito вернула HTTP 429",
                        retry_after_seconds=retry_after,
                    )
                if response.status_code == 401:
                    raise AvitoSessionError("JSON-пагинация Avito вернула HTTP 401")
                if response.status_code == 403:
                    if _is_blocked_html(response.text):
                        raise AvitoBlockedError("JSON-пагинация Avito вернула HTTP 403")
                    raise AvitoSessionError(
                        "JSON-пагинация Avito вернула HTTP 403 без признаков IP-блокировки",
                        retry_after_seconds=900,
                    )
                if response.status_code >= 500:
                    raise AvitoNetworkError(
                        f"JSON-пагинация Avito вернула HTTP {response.status_code}"
                    )
                if response.status_code != 200:
                    raise AvitoNetworkError(
                        "Неожиданный статус JSON-пагинации Avito: "
                        f"HTTP {response.status_code}"
                    )
                if _is_blocked_html(response.text):
                    raise AvitoBlockedError("JSON-пагинация Avito вернула страницу блокировки")
                try:
                    payload = response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise AvitoParseError(
                        "JSON-пагинация Avito ответила не JSON-данными"
                    ) from exc
                if catalog_from_api_response(payload) is None:
                    raise AvitoParseError(
                        "В ответе JSON-пагинации Avito отсутствует catalog"
                    )
                # A rejected or malformed optional API response must never mutate
                # the healthy Chromium context.  Import Set-Cookie only after the
                # response is known to be a valid catalog payload.
                await self._sync_curl_cookies_to_browser(session)
                return parse_api_response(payload)
            except AvitoBlockedError:
                raise
            except (CurlRequestError, AvitoNetworkError) as exc:
                last_error = exc
                if attempt < self._settings.request_retries:
                    delay = min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning(
                        "Ошибка JSON-пагинации Avito, повтор через %.1f с: %s",
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
        raise AvitoNetworkError(f"JSON-пагинация Avito недоступна: {last_error}")

    async def _extend_with_api_pages(
        self,
        first_page_items: list[AvitoItem],
        *,
        page_state: AvitoPageState,
        search_url: str,
        max_pages: int | None = None,
    ) -> list[AvitoItem]:
        page_limit = max_pages or self._settings.avito_api_max_pages
        if (
            not first_page_items
            or len(first_page_items) >= self._settings.max_results
            or not page_state.context
            or not page_state.api_params
            or page_limit <= 1
        ):
            return first_page_items

        session = await self._get_curl_session()
        await self._sync_browser_cookies_to_curl(session)
        result = {item.id: item for item in first_page_items}
        api_health_key = f"optional-api:{self._route_health_key()}"
        api_cooldown = self._route_health.quarantine_remaining(api_health_key)
        if api_cooldown:
            logger.info(
                "Необязательная JSON-пагинация Avito на паузе ещё %s с; "
                "используется успешная первая страница",
                api_cooldown,
            )
            return first_page_items
        for page_number in range(2, page_limit + 1):
            try:
                page_items = await self._request_api_page(
                    page_number=page_number,
                    page_state=page_state,
                    search_url=search_url,
                )
            except AvitoRateLimitedError as exc:
                retry_after = (
                    exc.retry_after_seconds
                    or self._settings.avito_rate_limit_cooldown_seconds
                )
                self._route_health.quarantine(
                    api_health_key,
                    retry_after,
                    "optional-api-rate-limit",
                )
                logger.warning(
                    "JSON-пагинация Avito остановлена на странице %s на %s с: %s. "
                    "Успешные результаты первой страницы сохранены.",
                    page_number,
                    retry_after,
                    exc,
                )
                break
            except AvitoError as exc:
                retry_after = (
                    exc.retry_after_seconds
                    or self._settings.avito_rate_limit_cooldown_seconds
                )
                self._route_health.quarantine(
                    api_health_key,
                    retry_after,
                    "optional-api-error",
                )
                logger.warning(
                    "JSON-пагинация Avito остановлена на странице %s на %s с: %s. "
                    "Успешные результаты первой страницы сохранены; браузерная "
                    "сессия не перезапускается ради необязательной пагинации.",
                    page_number,
                    retry_after,
                    exc,
                )
                break
            if not page_items:
                break
            before = len(result)
            result.update((item.id, item) for item in page_items)
            if len(result) == before or len(result) >= self._settings.max_results:
                break
        return list(result.values())

    async def _wait_for_browser_slot(self) -> None:
        """Backward-compatible entry point for the global Avito request limiter."""
        await self._before_avito_request()

    def _raise_if_cooling_down(self) -> None:
        if self._cooldown_until is None:
            return
        remaining = self._cooldown_until - asyncio.get_running_loop().time()
        if remaining <= 0:
            self._cooldown_until = None
            return
        retry_after_seconds = math.ceil(remaining)
        raise AvitoBlockedError(
            f"Avito на паузе ещё {retry_after_seconds} секунд после серии ошибок",
            retry_after_seconds=retry_after_seconds,
        )

    def _start_cooldown(self) -> None:
        loop = asyncio.get_running_loop()
        self._cooldown_until = loop.time() + self._settings.avito_cooldown_seconds

    async def _navigate_avito_page(
        self,
        page: Page,
        url: str,
        *,
        page_name: str,
        referer: str | None = None,
        on_blocked: BlockedCallback | None = None,
    ) -> tuple[int | None, str, bool]:
        if not self._settings.avito_browser_headless and page.url in {"", "about:blank"}:
            with suppress(PlaywrightError):
                await page.set_content(
                    """
                    <!doctype html><html lang="ru"><head><meta charset="utf-8">
                    <title>Avito Parser — подключение</title></head>
                    <body style="font:20px sans-serif;padding:40px;color:#333">
                    <h2>Подключение к Avito…</h2>
                    <p>Проверяется выбранный IP. Если прокси не ответит, бот автоматически
                    переключится на следующий адрес пула.</p></body></html>
                    """,
                    wait_until="domcontentloaded",
                    timeout=min(5_000, self._settings.request_timeout_seconds * 1000),
                )
        await self._before_avito_request()
        response = await page.goto(
            url,
            wait_until="commit",
            timeout=self._settings.request_timeout_seconds * 1000,
            referer=referer,
        )
        status = response.status if response is not None else None
        with suppress(PlaywrightTimeoutError):
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=min(10_000, self._settings.request_timeout_seconds * 1000),
            )
        html = await page.content()
        logger.info("Avito: %s открыта, HTTP %s", page_name, status)
        response_headers = response.headers if response is not None else None
        return await self._wait_then_reload_avito_page(
            page,
            status=status,
            html=html,
            page_name=page_name,
            on_blocked=on_blocked,
            headers=response_headers,
        )

    async def _wait_then_reload_avito_page(
        self,
        page: Page,
        *,
        status: int | None,
        html: str,
        page_name: str,
        on_blocked: BlockedCallback | None = None,
        headers: Mapping[str, object] | None = None,
        require_expected_dom: bool = False,
    ) -> tuple[int | None, str, bool]:
        """Return immediately on success; wait and reload only after an Avito error."""
        recovered_home = (
            page_name == AVITO_HOME_PAGE_NAME
            and status is not None
            and status < 400
            and _is_avito_url(page.url)
            and await _is_visually_loaded_avito_home(page, html)
        )
        if (
            page_name == AVITO_HOME_PAGE_NAME
            and status is not None
            and status < 400
            and _is_avito_url(page.url)
            and not recovered_home
        ):
            # `goto(wait_until="commit")` and DOMContentLoaded can both precede
            # hydration.  Wait for either a real home DOM or a visible block state
            # before marking browser warm-up complete.
            wait_for_function = getattr(page, "wait_for_function", None)
            if wait_for_function is not None:
                with suppress(PlaywrightError):
                    await wait_for_function(
                        AVITO_HOME_TERMINAL_SCRIPT,
                        timeout=self._settings.request_timeout_seconds * 1000,
                    )
                html = await page.content()
                recovered_home = await _is_visually_loaded_avito_home(page, html)
        recovered_search = (
            page_name == AVITO_SEARCH_PAGE_NAME
            and status is not None
            and status < 400
            and _is_avito_url(page.url)
            and await _is_visually_loaded_avito_search(page, html)
        )
        recovered_expected_page = recovered_home or recovered_search
        page_ready = (
            recovered_expected_page
            if page_name == AVITO_HOME_PAGE_NAME or require_expected_dom
            else _is_avito_page_ready(status, html, page.url)
            or recovered_expected_page
        )
        if page_ready:
            if recovered_expected_page and _is_blocked_html(html):
                logger.info(
                    "Avito: ожидаемая страница уже отображается; "
                    "остаточные признаки блокировки в HTML и URL игнорируются"
                )
            logger.info("Avito: %s успешно загружена без ожидания", page_name)
            return status, html, False

        if status == 401:
            raise AvitoSessionError("Avito отклонил текущую сессию (HTTP 401)")

        if (
            status == 429
            and not _is_transient_ip_problem_html(html)
            and not _requires_immediate_restart_html(html)
        ):
            raise self._rate_limit_error(headers)

        if status == 403 and not _is_blocked_html(html):
            diagnostic_path = await self._save_browser_diagnostic(page, status)
            raise AvitoSessionError(
                "Avito вернул HTTP 403 без известных признаков IP-блокировки",
                diagnostic_path=diagnostic_path,
                retry_after_seconds=900,
            )

        should_restart_immediately = _requires_immediate_restart_html(html) or (
            _is_blocked_page(status, html) and not _is_transient_ip_problem_html(html)
        )
        if should_restart_immediately:
            self._quarantine_current_route(
                seconds=self._settings.avito_ip_quarantine_seconds,
                reason="captcha" if _is_captcha_html(html) else "ip-block",
            )
            diagnostic_path = await self._save_browser_diagnostic(page, status)
            is_captcha = _is_captcha_html(html)
            logger.warning(
                (
                    "Avito показал капчу (%s, HTTP %s); "
                    if is_captcha
                    else "Avito заблокировал IP (%s, HTTP %s); "
                )
                +
                "переключаю пользователя и прокси без ожидания. Снимок: %s",
                page_name,
                status,
                diagnostic_path or "не сохранён",
            )
            error_type = (
                AvitoCaptchaRequiredError if is_captcha else AvitoHardBlockedError
            )
            blocked_error = error_type(
                (
                    f"Avito показал капчу: {page_name}, HTTP {status}; меняю пользователя"
                    if is_captcha
                    else f"Avito заблокировал IP: {page_name}, HTTP {status}; меняю прокси"
                ),
                diagnostic_path=diagnostic_path,
            )
            rotation_available = self._proxy_rotation_available()
            blocked_error.rotation_planned = rotation_available
            if rotation_available:
                raise _AvitoProxyRotationRequired(
                    "Avito потребовал немедленную смену пользователя и IP",
                    diagnostic_path=diagnostic_path,
                    notification_error=blocked_error if on_blocked is not None else None,
                )
            await self._replace_blocked_browser_identity(
                "жёсткая блокировка без доступной смены IP"
            )
            self._start_cooldown()
            if on_blocked is not None:
                try:
                    await on_blocked(blocked_error)
                except Exception:
                    logger.exception(
                        "Не удалось отправить уведомление о блокировке Avito"
                    )
            raise AvitoHardBlockedError(
                "Avito заблокировал текущую сессию, но смена IP недоступна",
                diagnostic_path=diagnostic_path,
                retry_after_seconds=self._settings.avito_cooldown_seconds,
            )

        if (
            status is not None
            and status < 400
            and _is_avito_url(page.url)
            and not _is_transient_ip_problem_html(html)
        ):
            diagnostic_path = await self._save_browser_diagnostic(page, status)
            raise AvitoParseError(
                f"Avito вернул HTTP {status}, но ожидаемый DOM ({page_name}) не появился",
                diagnostic_path=diagnostic_path,
            )

        if not _is_transient_ip_problem_html(html):
            raise AvitoNetworkError(
                f"Avito не открыл страницу {page_name}: HTTP {status}"
            )

        diagnostic_path: Path | None = None
        block_notified = False
        captcha_notified = False
        reload_number = 0
        reload_limit = (
            self._settings.avito_proxy_rotate_after_reloads
            if self._proxy_rotation_available() and _is_blocked_page(status, html)
            else self._settings.avito_error_reload_attempts
        )
        while True:
            is_captcha = _is_captcha_html(html)
            should_notify = not block_notified or (is_captcha and not captcha_notified)
            if _is_blocked_page(status, html) and should_notify:
                if diagnostic_path is None:
                    diagnostic_path = await self._save_browser_diagnostic(page, status)
                logger.warning(
                    (
                        "Avito запросил подтверждение пользователя (%s, HTTP %s). "
                        if is_captcha
                        else "Avito ограничил доступ (%s, HTTP %s). "
                    )
                    + "Вкладка останется открытой. Первый снимок: %s",
                    page_name,
                    status,
                    diagnostic_path or "не сохранён",
                )
                block_notified = True
                captcha_notified = captcha_notified or is_captcha
                if on_blocked is not None:
                    error_type = (
                        AvitoCaptchaRequiredError if is_captcha else AvitoBlockedError
                    )
                    blocked_error = error_type(
                        (
                            f"Avito просит нажать кнопку подтверждения: {page_name}, "
                            f"HTTP {status}"
                            if is_captcha
                            else f"Avito ограничил доступ: {page_name}, HTTP {status}"
                        ),
                        diagnostic_path=diagnostic_path,
                    )
                    try:
                        await on_blocked(blocked_error)
                    except Exception:
                        logger.exception(
                            "Не удалось отправить уведомление о блокировке Avito"
                        )

            reload_number += 1
            delay = self._settings.avito_page_reload_delay_seconds + random.uniform(
                0,
                self._settings.avito_page_reload_jitter_seconds,
            )
            logger.info(
                "Avito: %s вернула ошибку; повторное обновление %s через %.1f с",
                page_name,
                reload_number,
                delay,
            )
            await asyncio.sleep(delay)
            if page.is_closed():
                raise AvitoNetworkError(
                    "Вкладка Avito была закрыта во время ожидания обновления",
                    diagnostic_path=diagnostic_path,
                )
            try:
                await self._before_avito_request(explicit_delay_applied=True)
                response = await page.reload(
                    wait_until="domcontentloaded",
                    timeout=self._settings.request_timeout_seconds * 1000,
                )
                status = response.status if response is not None else None
                html = await page.content()
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                logger.warning("Не удалось обновить Avito: %s", exc)
                status = None

            recovered_home = (
                page_name == AVITO_HOME_PAGE_NAME
                and status is not None
                and status < 400
                and _is_avito_url(page.url)
                and await _is_visually_loaded_avito_home(
                    page,
                    html,
                    wait_timeout_ms=min(
                        5_000,
                        self._settings.request_timeout_seconds * 1000,
                    ),
                )
            )
            recovered_search = (
                page_name == AVITO_SEARCH_PAGE_NAME
                and status is not None
                and status < 400
                and _is_avito_url(page.url)
                and await _is_visually_loaded_avito_search(
                    page,
                    html,
                    wait_timeout_ms=min(
                        5_000,
                        self._settings.request_timeout_seconds * 1000,
                    ),
                )
            )
            recovered_expected_page = recovered_home or recovered_search
            if recovered_expected_page:
                html = await page.content()
            if _is_avito_page_ready(status, html, page.url) or recovered_expected_page:
                if recovered_expected_page and _is_blocked_html(html):
                    logger.info(
                        "Avito: после ожидания отображается ожидаемая страница; "
                        "остаточные признаки блокировки игнорируются"
                    )
                logger.info(
                    "Avito: %s готова после ожидания и %s обновлений, HTTP %s",
                    page_name,
                    reload_number,
                    status,
                )
                return status, html, block_notified

            logger.warning(
                "Avito пока не готов: HTTP %s, URL %s, неудач %s/%s",
                status,
                page.url,
                reload_number,
                reload_limit,
            )
            if reload_number >= reload_limit:
                self._quarantine_current_route(
                    seconds=self._settings.avito_ip_quarantine_seconds,
                    reason="transient-ip-problem",
                )
                if diagnostic_path is None:
                    diagnostic_path = await self._save_browser_diagnostic(page, status)
                if self._proxy_rotation_available() and block_notified:
                    raise _AvitoProxyRotationRequired(
                        f"Avito не открылся после {reload_number} перезагрузок; "
                        "требуется сменить IP",
                        diagnostic_path=diagnostic_path,
                    )
                if block_notified:
                    await self._replace_blocked_browser_identity(
                        "блокировка без доступной смены IP"
                    )
                self._start_cooldown()
                cooldown = self._settings.avito_cooldown_seconds
                logger.warning(
                    "Avito не открылся после %s перезагрузок; пауза на %s с",
                    reload_number,
                    cooldown,
                )
                raise AvitoBlockedError(
                    f"Avito не открылся после {reload_number} перезагрузок; "
                    f"парсер приостановлен на {cooldown // 3600} ч.",
                    diagnostic_path=diagnostic_path,
                    retry_after_seconds=cooldown,
                )

    async def _open_avito_home(
        self,
        page: Page,
        *,
        on_blocked: BlockedCallback | None = None,
    ) -> tuple[int | None, str, bool]:
        return await self._navigate_avito_page(
            page,
            f"{AVITO_BASE_URL}/",
            page_name=AVITO_HOME_PAGE_NAME,
            on_blocked=on_blocked,
        )

    async def open_manual_verification_page(self, url: str) -> tuple[Page, int | None, int | None]:
        """Open Avito in a temporary session for user-completed verification."""
        await self._prepare_new_user_session()
        await self._start_browser()
        await self._start_browser_session()
        assert self._browser_context is not None
        page = await self._acquire_browser_page()
        home_status, _, _ = await self._open_avito_home(page)
        search_status, _, _ = await self._navigate_avito_page(
            page,
            url,
            page_name="страница поиска",
            referer=f"{AVITO_BASE_URL}/",
        )
        return page, home_status, search_status

    async def _save_browser_diagnostic(self, page: Page, status: int | None) -> Path | None:
        if page.url in {"", "about:blank"}:
            logger.warning("Снимок Avito пропущен: вкладка осталась about:blank")
            return None
        diagnostic_dir = self._settings.database_path.parent / "diagnostics"
        try:
            ensure_private_directory(diagnostic_dir)
        except OSError as exc:
            logger.warning("Не удалось подготовить каталог диагностики Avito: %s", exc)
            return None
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        stem = f"avito-{status or 'unknown'}-{timestamp}"
        screenshot_path = diagnostic_dir / f"{stem}.png"
        html_path = diagnostic_dir / f"{stem}.html"
        metadata_path = diagnostic_dir / f"{stem}.json"
        try:
            html = await page.content()
            write_private_text(html_path, html)
            write_private_json(
                metadata_path,
                {
                    "capturedAt": datetime.now().astimezone().isoformat(),
                    "status": status,
                    "url": page.url,
                    "route": self.last_route,
                    "identityId": self._ensure_browser_identity().identity_id,
                },
            )
        except (AttributeError, OSError, PlaywrightError) as exc:
            logger.warning("Не удалось сохранить HTML-диагностику Avito: %s", exc)
        screenshot_saved = False
        try:
            await page.screenshot(
                path=str(screenshot_path),
                full_page=False,
                timeout=min(5_000, self._settings.request_timeout_seconds * 1000),
            )
            harden_file_permissions(screenshot_path)
            screenshot_saved = True
            logger.warning("Диагностический снимок Avito сохранён: %s", screenshot_path)
        except (AttributeError, OSError, PlaywrightError) as exc:
            logger.warning("Не удалось сохранить снимок Avito: %s", exc)
        finally:
            prune_avito_diagnostic_bundles(diagnostic_dir)
        return screenshot_path if screenshot_saved else None

    async def _search_route(
        self,
        url: str,
        headers: dict[str, str],
        *,
        use_proxy: bool,
    ) -> list[AvitoItem]:
        session, request_proxy = await self._get_session(use_proxy=use_proxy)
        route_key = self._route_health_key(
            request_proxy if use_proxy else None,
            use_current_route=False,
        )
        last_error: Exception | None = None
        for attempt in range(1, self._settings.request_retries + 1):
            try:
                await self._before_avito_request(route_key=route_key)
                async with session.get(
                    url,
                    headers=headers,
                    proxy=request_proxy,
                    allow_redirects=True,
                ) as response:
                    body = await response.text(errors="replace")
                    if response.status == 429:
                        raise self._rate_limit_error(
                            response.headers,
                            route_key=route_key,
                        )
                    if response.status == 401:
                        raise AvitoSessionError("Avito вернул HTTP 401")
                    if response.status == 403:
                        if _is_blocked_html(body):
                            self._quarantine_current_route(
                                seconds=self._settings.avito_ip_quarantine_seconds,
                                reason="http-403",
                                route_key=route_key,
                            )
                            raise AvitoBlockedError("Avito вернул HTTP 403")
                        raise AvitoSessionError(
                            "Avito вернул HTTP 403 без признаков IP-блокировки",
                            retry_after_seconds=900,
                        )
                    if response.status >= 500:
                        raise AvitoNetworkError(f"Avito вернул HTTP {response.status}")
                    if response.status != 200:
                        raise AvitoNetworkError(f"Неожиданный HTTP-статус Avito: {response.status}")
                    items = parse_search_html(body)[: self._settings.max_results]
                    self._record_route_success(route_key)
                    return items
            except AvitoBlockedError:
                raise
            except (TimeoutError, aiohttp.ClientError, AvitoNetworkError) as exc:
                last_error = exc
                if attempt < self._settings.request_retries:
                    delay = min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning("Ошибка запроса Avito, повтор через %.1f с: %s", delay, exc)
                    await asyncio.sleep(delay)
        raise AvitoNetworkError(f"Avito недоступен после повторов: {last_error}")
