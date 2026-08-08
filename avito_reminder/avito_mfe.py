from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import AvitoItem

AVITO_BASE_URL = "https://www.avito.ru"


@dataclass(frozen=True, slots=True)
class AvitoPageState:
    """Structured search data embedded into Avito's first HTML page."""

    items: tuple[AvitoItem, ...]
    context: str | None
    api_params: dict[str, str]


def _price_from_value(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def _item_id(value: object, url: str) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        normalized = str(value).strip()
        if normalized:
            return normalized
    if isinstance(value, dict):
        for key in ("value", "id"):
            nested = _item_id(value.get(key), url)
            if nested:
                return nested
    match = re.search(r"_(\d{6,})$", urlparse(url).path.rstrip("/"))
    return match.group(1) if match else None


def _nested_string(value: object, *path: str) -> str | None:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if not isinstance(current, str):
        return None
    normalized = " ".join(current.split())
    return normalized or None


def _first_image_url(value: object) -> str | None:
    if isinstance(value, str):
        return value if value.startswith(("http://", "https://")) else None
    if isinstance(value, list):
        for child in value:
            if result := _first_image_url(child):
                return result
        return None
    if not isinstance(value, dict):
        return None

    preferred_keys = (
        "imageLargeUrl",
        "imageUrl",
        "imageLargeVipUrl",
        "imageVipUrl",
        "640x480",
        "432x324",
        "url",
        "src",
    )
    for key in preferred_keys:
        if result := _first_image_url(value.get(key)):
            return result
    for child in value.values():
        if result := _first_image_url(child):
            return result
    return None


def _parse_catalog_item(raw: object) -> AvitoItem | None:
    if not isinstance(raw, dict):
        return None

    raw_url = raw.get("urlPath") or raw.get("url")
    title = raw.get("title") or raw.get("name")
    if not isinstance(raw_url, str) or not isinstance(title, str):
        return None

    url = urljoin(AVITO_BASE_URL, raw_url)
    item_id = _item_id(raw.get("id"), url)
    title = " ".join(title.split())
    if not item_id or not title:
        return None

    price_details = raw.get("priceDetailed")
    price_value = price_details.get("value") if isinstance(price_details, dict) else None
    price = _price_from_value(price_value if price_value is not None else raw.get("price"))
    location = (
        _nested_string(raw, "addressDetailed", "locationName")
        or _nested_string(raw, "location", "name")
        or _nested_string(raw, "geo", "formattedAddress")
    )
    image_url = _first_image_url(raw.get("gallery")) or _first_image_url(raw.get("images"))

    return AvitoItem(
        id=item_id,
        title=title,
        price=price,
        url=url,
        location=location,
        image_url=image_url,
    )


def parse_catalog(catalog: object) -> list[AvitoItem]:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        return []
    result: dict[str, AvitoItem] = {}
    for raw_item in catalog["items"]:
        item = _parse_catalog_item(raw_item)
        if item is not None:
            result[item.id] = item
    return list(result.values())


def catalog_from_api_response(payload: object) -> object:
    if not isinstance(payload, dict):
        return None
    catalog = payload.get("catalog")
    if isinstance(catalog, dict):
        return catalog
    result = payload.get("result")
    return result.get("catalog") if isinstance(result, dict) else None


def parse_api_response(payload: object) -> list[AvitoItem]:
    return parse_catalog(catalog_from_api_response(payload))


def _stringify_parameter(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def build_api_params(search_core: object) -> dict[str, str]:
    if not isinstance(search_core, dict):
        return {}

    result: dict[str, str] = {}
    for key in (
        "categoryId",
        "locationId",
        "verticalCategoryId",
        "rootCategoryId",
        "localPriority",
        "geoCoords",
    ):
        value = search_core.get(key)
        if value not in (None, "", []):
            result[key] = _stringify_parameter(value)

    simple_mappings = {
        "priceMax": "pmax",
        "priceMin": "pmin",
        "owner": "user",
        "searchRadius": "radius",
    }
    for source, target in simple_mappings.items():
        value = search_core.get(source)
        if value not in (None, "", [], False):
            result[target] = _stringify_parameter(value)
    if search_core.get("withDeliveryOnly"):
        result["cd"] = "1"

    filters = search_core.get("params")
    if isinstance(filters, dict):
        for key, value in filters.items():
            if value in (None, "", []):
                continue
            if isinstance(value, list):
                value = value[-1]
            result[f"params[{key}]"] = _stringify_parameter(value)
    return result


def _loader_data(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    loader_data = payload.get("loaderData")
    if not isinstance(loader_data, dict):
        return None
    data = loader_data.get("data")
    return data if isinstance(data, dict) else None


def extract_page_state(source: str) -> AvitoPageState | None:
    """Extract Avito MFE state without depending on generated CSS class names."""
    soup = BeautifulSoup(source, "html.parser")
    scripts = soup.select('script[type="mime/invalid"][data-mfe-state="true"]')
    for script in scripts:
        raw = script.string if script.string is not None else script.get_text()
        if not raw or "sandbox" in raw:
            continue
        try:
            payload = json.loads(html_lib.unescape(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        data = _loader_data(payload)
        if data is None:
            continue
        catalog = data.get("catalog")
        if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
            continue
        context = data.get("context")
        return AvitoPageState(
            items=tuple(parse_catalog(catalog)),
            context=context if isinstance(context, str) and context else None,
            api_params=build_api_params(data.get("searchCore")),
        )
    return None
