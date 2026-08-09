from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import shutil
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlsplit

import aiohttp
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup, Tag
from curl_cffi.requests import AsyncSession as CurlAsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestError
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

from .avito_mfe import (
    AvitoPageState,
    catalog_from_api_response,
    extract_page_state,
    parse_api_response,
)
from .config import Settings
from .models import AvitoItem

logger = logging.getLogger(__name__)

AVITO_BASE_URL = "https://www.avito.ru"
AVITO_BLOCK_HTTP_STATUSES = frozenset({401, 403, 429})
AVITO_BLOCK_MARKERS = (
    "доступ ограничен: проблема с ip",
    "продолжить для решения капчи",
    'data-marker="captcha"',
    "captcha challenge",
    "too many requests",
)


def _is_blocked_html(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in AVITO_BLOCK_MARKERS)


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


def _has_target_search_query(current_url: str, target_url: str) -> bool:
    current_query = parse_qs(urlsplit(current_url).query).get("q")
    target_query = parse_qs(urlsplit(target_url).query).get("q")
    return bool(target_query and current_query == target_query)


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


class AvitoBlockedError(AvitoError):
    """Avito requested a captcha or blocked the current IP."""


class AvitoParseError(AvitoError):
    """The response did not contain a supported search result format."""


class _AvitoProxyRotationRequired(AvitoBlockedError):
    """Internal signal indicating that the current Avito route should be replaced."""


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
    if _is_blocked_html(html):
        raise AvitoBlockedError("Avito ограничил доступ с текущего IP или запросил капчу")

    page_state = extract_page_state(html)
    if page_state is not None:
        return list(page_state.items)

    soup = BeautifulSoup(html, "html.parser")
    items = _parse_cards(soup) or _parse_json_ld(soup)
    if items:
        return items

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


def _proxy_label(proxy_url: str | None) -> str:
    if not proxy_url:
        return "direct"
    parsed = urlsplit(proxy_url)
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


def _playwright_proxy(proxy_url: str) -> dict[str, str]:
    parsed = urlsplit(proxy_url)
    assert parsed.hostname is not None and parsed.port is not None
    result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username is not None:
        result["username"] = unquote(parsed.username)
    if parsed.password is not None:
        result["password"] = unquote(parsed.password)
    return result


class AvitoClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._avito_proxies = _AvitoProxyPool(settings)
        self._direct_session: aiohttp.ClientSession | None = None
        self._proxy_session: aiohttp.ClientSession | None = None
        self._curl_session: CurlAsyncSession | None = None
        self._playwright: Playwright | None = None
        self._browser_context: BrowserContext | None = None
        self._browser_lock = asyncio.Lock()
        self._browser_warmed_up = False
        self._last_browser_request_at: float | None = None
        self._cooldown_until: float | None = None
        self.last_route: str | None = None

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
        proxy_url = self._avito_proxies.current
        browser_args = ["--disable-dev-shm-usage"]
        if proxy_url is None:
            browser_args.insert(0, "--no-proxy-server")
        self._playwright = await async_playwright().start()
        try:
            self._browser_context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                executable_path=executable_path,
                headless=self._settings.avito_browser_headless,
                args=browser_args,
                proxy=_playwright_proxy(proxy_url) if proxy_url else None,
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
            "Chromium для Avito запущен: route=%s, executable=%s, headless=%s, profile=%s",
            _proxy_label(proxy_url),
            executable_path or "playwright",
            self._settings.avito_browser_headless,
            profile_path,
        )

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
    ) -> list[AvitoItem]:
        if self._settings.avito_transport in {"browser", "hybrid"}:
            route_kind = "proxy" if self._avito_proxies.current else "direct"
            self.last_route = (
                f"chromium+curl-{route_kind}"
                if self._settings.avito_transport == "hybrid"
                else f"chromium-{route_kind}"
            )
            return await self._search_browser(url, on_blocked=on_blocked)

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

    async def _search_browser(
        self,
        url: str,
        *,
        on_blocked: BlockedCallback | None = None,
    ) -> list[AvitoItem]:
        async with self._browser_lock:
            self._raise_if_cooling_down()
            await self._wait_for_browser_slot()
            rotations = 0
            while True:
                await self._start_browser()
                try:
                    return await self._search_browser_with_current_proxy(
                        url,
                        on_blocked=on_blocked,
                    )
                except _AvitoProxyRotationRequired as exc:
                    if (
                        not self._proxy_rotation_available()
                        or rotations >= self._settings.avito_proxy_max_rotations
                    ):
                        self._start_cooldown()
                        cooldown = self._settings.avito_cooldown_seconds
                        raise AvitoBlockedError(
                            f"Avito продолжил блокировать доступ после {rotations} смен IP; "
                            f"парсер приостановлен на {max(1, cooldown // 3600)} ч.",
                            diagnostic_path=exc.diagnostic_path,
                            retry_after_seconds=cooldown,
                        ) from exc
                    rotations += 1
                    await self._rotate_avito_proxy(rotations)

    async def _acquire_browser_page(self) -> Page:
        """Reuse Chromium's startup tab and remove duplicate about:blank tabs."""
        assert self._browser_context is not None
        blank_pages = [
            page
            for page in self._browser_context.pages
            if not page.is_closed() and page.url in {"", "about:blank"}
        ]
        if blank_pages:
            page = blank_pages[0]
            for duplicate in blank_pages[1:]:
                await duplicate.close()
            return page
        return await self._browser_context.new_page()

    async def _search_browser_with_current_proxy(
        self,
        url: str,
        *,
        on_blocked: BlockedCallback | None = None,
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
                    status, html, _ = await self._navigate_avito_page(
                        page,
                        url,
                        page_name="страница поиска после главной",
                        referer=f"{AVITO_BASE_URL}/",
                        on_blocked=on_blocked,
                    )
                if status in AVITO_BLOCK_HTTP_STATUSES:
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
                    page_state = extract_page_state(html)
                    items = parse_search_html(html)
                    if self._settings.avito_transport == "hybrid" and page_state is not None:
                        items = await self._extend_with_api_pages(
                            items,
                            page_state=page_state,
                            search_url=url,
                        )
                    return items[: self._settings.max_results]
                except (AvitoBlockedError, AvitoParseError) as exc:
                    exc.diagnostic_path = await self._save_browser_diagnostic(page, status)
                    raise
            except AvitoBlockedError:
                raise
            except (PlaywrightTimeoutError, PlaywrightError, AvitoNetworkError) as exc:
                last_error = exc
                if (
                    page.url in {"", "about:blank"}
                    and self._avito_proxies.current is not None
                    and self._proxy_rotation_available()
                ):
                    logger.warning(
                        "Прокси не смог открыть Avito: вкладка осталась about:blank; "
                        "переключаю IP без создания снимка"
                    )
                    raise _AvitoProxyRotationRequired(
                        "Прокси не открыл Avito, вкладка осталась about:blank; "
                        "требуется сменить IP"
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
            finally:
                await page.close()

        raise AvitoNetworkError(
            f"Avito недоступен через Chromium: {last_error}",
            diagnostic_path=last_diagnostic_path,
        )

    def _proxy_rotation_available(self) -> bool:
        return (
            self._settings.avito_proxy_mode != "direct"
            and self._settings.avito_proxy_rotation_enabled
            and bool(
                self._settings.avito_proxy_pool
                or self._settings.avito_proxy_change_url
            )
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
                session.get(change_url, allow_redirects=True) as response,
            ):
                if response.status >= 400:
                    raise AvitoNetworkError(
                        "Сервис смены IP вернул ошибку "
                        f"HTTP {response.status}"
                    )
        except aiohttp.ClientError as exc:
            raise AvitoNetworkError(
                f"Не удалось вызвать сервис смены IP: {type(exc).__name__}"
            ) from exc

    async def _rotate_avito_proxy(self, rotation_number: int) -> None:
        previous_route = _proxy_label(self._avito_proxies.current)
        await self._close_browser_network()
        await self._call_proxy_change_url()
        next_proxy = self._avito_proxies.rotate()
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
        route_kind = "proxy" if next_proxy else "direct"
        self.last_route = (
            f"chromium+curl-{route_kind}"
            if self._settings.avito_transport == "hybrid"
            else f"chromium-{route_kind}"
        )

    async def _get_curl_session(self) -> CurlAsyncSession:
        if self._curl_session is not None:
            return self._curl_session

        proxies: dict[str, str] | None = None
        proxy_url = self._avito_proxies.current
        if proxy_url is not None:
            proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
        self._curl_session = CurlAsyncSession(
            impersonate=self._settings.avito_http_impersonate,
            timeout=self._settings.request_timeout_seconds,
            trust_env=False,
            proxies=proxies,
        )
        return self._curl_session

    async def _sync_browser_cookies_to_curl(self, session: CurlAsyncSession) -> None:
        assert self._browser_context is not None
        browser_cookies = await self._browser_context.cookies([AVITO_BASE_URL])
        for cookie in browser_cookies:
            expires_value = cookie.get("expires")
            expires = (
                int(expires_value)
                if isinstance(expires_value, (int, float)) and expires_value > 0
                else None
            )
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain") or ".avito.ru",
                path=cookie.get("path") or "/",
                secure=bool(cookie.get("secure")),
                expires=expires,
            )
        logger.debug("В HTTP-сессию Avito синхронизировано cookies: %s", len(browser_cookies))

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
                if response.status_code in AVITO_BLOCK_HTTP_STATUSES:
                    raise AvitoBlockedError(
                        f"JSON-пагинация Avito вернула HTTP {response.status_code}"
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
    ) -> list[AvitoItem]:
        if (
            not first_page_items
            or len(first_page_items) >= self._settings.max_results
            or not page_state.context
            or not page_state.api_params
            or self._settings.avito_api_max_pages <= 1
        ):
            return first_page_items

        session = await self._get_curl_session()
        await self._sync_browser_cookies_to_curl(session)
        result = {item.id: item for item in first_page_items}
        for page_number in range(2, self._settings.avito_api_max_pages + 1):
            try:
                page_items = await self._request_api_page(
                    page_number=page_number,
                    page_state=page_state,
                    search_url=search_url,
                )
            except AvitoBlockedError as exc:
                if self._proxy_rotation_available():
                    raise _AvitoProxyRotationRequired(str(exc)) from exc
                logger.warning(
                    "JSON-пагинация Avito заблокирована на странице %s: %s. "
                    "Результаты первой страницы сохранены.",
                    page_number,
                    exc,
                )
                break
            except AvitoError as exc:
                logger.warning(
                    "JSON-пагинация Avito остановлена на странице %s: %s. "
                    "Результаты первой страницы сохранены.",
                    page_number,
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
        loop = asyncio.get_running_loop()
        if self._last_browser_request_at is not None:
            minimum = self._settings.avito_min_request_interval_seconds
            jitter = random.uniform(0, self._settings.avito_request_jitter_seconds)
            remaining = minimum + jitter - (loop.time() - self._last_browser_request_at)
            if remaining > 0:
                logger.info("Пауза %.1f с перед следующим запросом Avito", remaining)
                await asyncio.sleep(remaining)
        self._last_browser_request_at = loop.time()

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
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self._settings.request_timeout_seconds * 1000,
            referer=referer,
        )
        status = response.status if response is not None else None
        html = await page.content()
        logger.info("Avito: %s открыта, HTTP %s", page_name, status)
        return await self._wait_then_reload_avito_page(
            page,
            status=status,
            html=html,
            page_name=page_name,
            on_blocked=on_blocked,
        )

    async def _wait_then_reload_avito_page(
        self,
        page: Page,
        *,
        status: int | None,
        html: str,
        page_name: str,
        on_blocked: BlockedCallback | None = None,
    ) -> tuple[int | None, str, bool]:
        """Return immediately on success; wait and reload only after an Avito error."""
        if _is_avito_page_ready(status, html, page.url):
            logger.info("Avito: %s успешно загружена без ожидания", page_name)
            return status, html, False

        diagnostic_path: Path | None = None
        block_notified = False
        reload_number = 0
        reload_limit = (
            self._settings.avito_proxy_rotate_after_reloads
            if self._proxy_rotation_available() and _is_blocked_page(status, html)
            else self._settings.avito_error_reload_attempts
        )
        while True:
            if _is_blocked_page(status, html) and not block_notified:
                diagnostic_path = await self._save_browser_diagnostic(page, status)
                logger.warning(
                    "Avito ограничил доступ (%s, HTTP %s). "
                    "Вкладка останется открытой. Первый снимок: %s",
                    page_name,
                    status,
                    diagnostic_path or "не сохранён",
                )
                block_notified = True
                if on_blocked is not None:
                    blocked_error = AvitoBlockedError(
                        f"Avito ограничил доступ: {page_name}, HTTP {status}",
                        diagnostic_path=diagnostic_path,
                    )
                    try:
                        await on_blocked(blocked_error)
                    except Exception:
                        logger.exception(
                            "Не удалось отправить уведомление о блокировке Avito"
                        )

            reload_number += 1
            delay = self._settings.avito_page_reload_delay_seconds
            logger.info(
                "Avito: %s вернула ошибку; повторное обновление %s через %s с",
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
                response = await page.reload(
                    wait_until="domcontentloaded",
                    timeout=self._settings.request_timeout_seconds * 1000,
                )
                status = response.status if response is not None else None
                html = await page.content()
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                logger.warning("Не удалось обновить Avito: %s", exc)
                status = None

            if _is_avito_page_ready(status, html, page.url):
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
                if diagnostic_path is None:
                    diagnostic_path = await self._save_browser_diagnostic(page, status)
                if self._proxy_rotation_available() and block_notified:
                    raise _AvitoProxyRotationRequired(
                        f"Avito не открылся после {reload_number} перезагрузок; "
                        "требуется сменить IP",
                        diagnostic_path=diagnostic_path,
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
            page_name="главная страница",
            on_blocked=on_blocked,
        )

    async def open_manual_verification_page(self, url: str) -> tuple[Page, int | None, int | None]:
        """Open Avito in the persistent profile for a user-completed verification."""
        await self._start_browser()
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
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        screenshot_path = diagnostic_dir / f"avito-{status or 'unknown'}-{timestamp}.png"
        try:
            await page.screenshot(
                path=str(screenshot_path),
                full_page=False,
                timeout=min(5_000, self._settings.request_timeout_seconds * 1000),
            )
            logger.warning("Диагностический снимок Avito сохранён: %s", screenshot_path)
            return screenshot_path
        except PlaywrightError as exc:
            logger.warning("Не удалось сохранить снимок Avito: %s", exc)
            return None

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
