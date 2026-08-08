from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import shutil
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from urllib.parse import urlencode, urljoin, urlparse, urlsplit

import aiohttp
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup, Tag
from playwright.async_api import (
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

from .config import Settings
from .models import AvitoItem

logger = logging.getLogger(__name__)

AVITO_BASE_URL = "https://www.avito.ru"


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


class AvitoNetworkError(AvitoError):
    """Avito could not be reached."""


class AvitoBlockedError(AvitoError):
    """Avito requested a captcha or blocked the current IP."""


class AvitoParseError(AvitoError):
    """The response did not contain a supported search result format."""


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
    lowered = html.lower()
    block_markers = (
        "доступ ограничен: проблема с ip",
        "продолжить для решения капчи",
        'data-marker="captcha"',
        "captcha challenge",
        "too many requests",
    )
    if any(marker in lowered for marker in block_markers):
        raise AvitoBlockedError("Avito ограничил доступ с текущего IP или запросил капчу")

    soup = BeautifulSoup(html, "html.parser")
    items = _parse_cards(soup) or _parse_json_ld(soup)
    if items:
        return items

    page_text = " ".join(soup.get_text(" ", strip=True).lower().split())
    empty_markers = ("ничего не найдено", "объявлений не найдено", "нет подходящих объявлений")
    if any(marker in page_text for marker in empty_markers):
        return []
    raise AvitoParseError("Avito ответил в неизвестном формате: карточки объявлений не найдены")


class AvitoClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._direct_session: aiohttp.ClientSession | None = None
        self._proxy_session: aiohttp.ClientSession | None = None
        self._playwright: Playwright | None = None
        self._browser_context: BrowserContext | None = None
        self._browser_lock = asyncio.Lock()
        self._browser_warmed_up = False
        self.last_route: str | None = None

    async def __aenter__(self) -> AvitoClient:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._settings.avito_transport == "browser":
            await self._start_browser()
        else:
            await self._get_session(use_proxy=self._routes()[0])

    async def close(self) -> None:
        for session in (self._direct_session, self._proxy_session):
            if session and not session.closed:
                await session.close()
        if self._browser_context is not None:
            await self._browser_context.close()
            self._browser_context = None
            self._browser_warmed_up = False
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _start_browser(self) -> None:
        if self._browser_context is not None:
            return

        profile_path = self._settings.avito_browser_profile_path
        profile_path.mkdir(parents=True, exist_ok=True)
        executable_path = resolve_chromium_executable(self._settings)
        self._playwright = await async_playwright().start()
        try:
            self._browser_context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                executable_path=executable_path,
                headless=self._settings.avito_browser_headless,
                args=["--no-proxy-server", "--disable-dev-shm-usage"],
                locale="ru-RU",
                viewport={"width": 1365, "height": 900},
                accept_downloads=False,
            )
        except PlaywrightError as exc:
            await self._playwright.stop()
            self._playwright = None
            executable_hint = executable_path or "встроенный Chromium Playwright"
            raise AvitoNetworkError(
                f"Не удалось запустить Chromium ({executable_hint}): {exc}"
            ) from exc

        logger.info(
            "Chromium для Avito запущен напрямую: executable=%s, headless=%s, profile=%s",
            executable_path or "playwright",
            self._settings.avito_browser_headless,
            profile_path,
        )

    def _routes(self) -> tuple[bool, ...]:
        mode = self._settings.avito_proxy_mode
        if mode == "proxy":
            return (True,)
        if mode == "fallback" and self._settings.http_proxy:
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

    async def search(self, url: str) -> list[AvitoItem]:
        if self._settings.avito_transport == "browser":
            self.last_route = "chromium-direct"
            return await self._search_browser(url)

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

    async def _search_browser(self, url: str) -> list[AvitoItem]:
        async with self._browser_lock:
            await self._start_browser()
            assert self._browser_context is not None
            last_error: Exception | None = None

            for attempt in range(1, self._settings.request_retries + 1):
                page = await self._browser_context.new_page()
                try:
                    if not self._browser_warmed_up:
                        home_status = await self._open_avito_home(page)
                        if home_status in {401, 403, 429}:
                            await self._save_browser_diagnostic(page, home_status)
                            raise AvitoBlockedError(
                                f"Главная страница Avito вернула HTTP {home_status}"
                            )
                        if home_status is not None and home_status >= 400:
                            raise AvitoNetworkError(
                                f"Главная страница Avito вернула HTTP {home_status}"
                            )
                        self._browser_warmed_up = True

                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self._settings.request_timeout_seconds * 1000,
                        referer=f"{AVITO_BASE_URL}/",
                    )
                    status = response.status if response is not None else None
                    if status in {401, 403, 429}:
                        await self._save_browser_diagnostic(page, status)
                        raise AvitoBlockedError(f"Chromium получил от Avito HTTP {status}")
                    if status is not None and status >= 500:
                        raise AvitoNetworkError(f"Chromium получил от Avito HTTP {status}")
                    if status is not None and status >= 400:
                        raise AvitoNetworkError(f"Неожиданный HTTP-статус Avito: {status}")

                    with suppress(PlaywrightTimeoutError):
                        await page.wait_for_selector(
                            '[data-marker="item"], [data-item-id][itemtype*="Product"]',
                            state="attached",
                            timeout=min(8_000, self._settings.request_timeout_seconds * 1000),
                        )
                    html = await page.content()
                    try:
                        return parse_search_html(html)[: self._settings.max_results]
                    except (AvitoBlockedError, AvitoParseError):
                        await self._save_browser_diagnostic(page, status)
                        raise
                except AvitoBlockedError:
                    raise
                except (PlaywrightTimeoutError, PlaywrightError, AvitoNetworkError) as exc:
                    last_error = exc
                    if attempt < self._settings.request_retries:
                        delay = min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                        logger.warning(
                            "Ошибка Chromium-запроса Avito, повтор через %.1f с: %s",
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                finally:
                    await page.close()

            raise AvitoNetworkError(f"Avito недоступен через Chromium: {last_error}")

    async def _open_avito_home(self, page: Page) -> int | None:
        response = await page.goto(
            f"{AVITO_BASE_URL}/",
            wait_until="domcontentloaded",
            timeout=self._settings.request_timeout_seconds * 1000,
        )
        status = response.status if response is not None else None
        logger.info("Главная страница Avito открыта через Chromium: HTTP %s", status)
        return status

    async def open_manual_verification_page(self, url: str) -> tuple[Page, int | None, int | None]:
        """Open Avito in the persistent profile for a user-completed verification."""
        await self._start_browser()
        assert self._browser_context is not None
        page = await self._browser_context.new_page()
        home_status = await self._open_avito_home(page)
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self._settings.request_timeout_seconds * 1000,
            referer=f"{AVITO_BASE_URL}/",
        )
        search_status = response.status if response is not None else None
        return page, home_status, search_status

    async def _save_browser_diagnostic(self, page: Page, status: int | None) -> None:
        diagnostic_dir = self._settings.database_path.parent / "diagnostics"
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        screenshot_path = diagnostic_dir / f"avito-{status or 'unknown'}-{timestamp}.png"
        try:
            await page.screenshot(path=str(screenshot_path), full_page=False)
            logger.warning("Диагностический снимок Avito сохранён: %s", screenshot_path)
        except PlaywrightError as exc:
            logger.warning("Не удалось сохранить снимок Avito: %s", exc)

    async def _search_route(
        self,
        url: str,
        headers: dict[str, str],
        *,
        use_proxy: bool,
    ) -> list[AvitoItem]:
        session, request_proxy = await self._get_session(use_proxy=use_proxy)
        last_error: Exception | None = None
        for attempt in range(1, self._settings.request_retries + 1):
            try:
                async with session.get(
                    url,
                    headers=headers,
                    proxy=request_proxy,
                    allow_redirects=True,
                ) as response:
                    body = await response.text(errors="replace")
                    if response.status in {401, 403, 429}:
                        raise AvitoBlockedError(f"Avito вернул HTTP {response.status}")
                    if response.status >= 500:
                        raise AvitoNetworkError(f"Avito вернул HTTP {response.status}")
                    if response.status != 200:
                        raise AvitoNetworkError(f"Неожиданный HTTP-статус Avito: {response.status}")
                    return parse_search_html(body)[: self._settings.max_results]
            except AvitoBlockedError:
                raise
            except (TimeoutError, aiohttp.ClientError, AvitoNetworkError) as exc:
                last_error = exc
                if attempt < self._settings.request_retries:
                    delay = min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning("Ошибка запроса Avito, повтор через %.1f с: %s", delay, exc)
                    await asyncio.sleep(delay)
        raise AvitoNetworkError(f"Avito недоступен после повторов: {last_error}")
