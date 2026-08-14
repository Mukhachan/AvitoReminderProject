import html
import json

import pytest

from avito_reminder.avito_mfe import extract_page_state


def _catalog(item_id: int = 9876543210) -> dict[str, object]:
    return {
        "items": [
            {
                "id": item_id,
                "urlPath": f"/moskva/telefony/test_phone_{item_id}",
                "title": "Тестовый телефон",
                "priceDetailed": {"value": 42_000},
                "addressDetailed": {"locationName": "Москва"},
            }
        ]
    }


def _metadata() -> dict[str, object]:
    return {
        "context": "offline-context",
        "searchCore": {
            "categoryId": 99,
            "locationId": 637640,
            "priceMin": 10_000,
        },
    }


def _script(payload: object, attributes: str = 'data-mfe-state="true"') -> str:
    return f"<script {attributes}>{json.dumps(payload, ensure_ascii=False)}</script>"


@pytest.mark.parametrize(
    "attributes",
    [
        'type="mime/invalid" data-mfe-state="true"',
        'data-extra="first" data-mfe-state="true" type="application/json"',
        'type="text/json" defer data-mfe-state="1"',
        "data-mfe-state",
    ],
)
def test_extract_page_state_accepts_mfe_script_attribute_and_type_variants(
    attributes: str,
) -> None:
    payload = {"loaderData": {"data": {**_metadata(), "catalog": _catalog()}}}

    state = extract_page_state(_script(payload, attributes))

    assert state is not None
    assert [item.id for item in state.items] == ["9876543210"]
    assert state.catalog_item_count == 1
    assert state.context == "offline-context"
    assert state.api_params == {
        "categoryId": "99",
        "locationId": "637640",
        "pmin": "10000",
    }


def test_extract_page_state_decodes_html_escaped_json() -> None:
    payload = {"loaderData": {"data": {**_metadata(), "catalog": _catalog()}}}
    escaped = html.escape(json.dumps(payload, ensure_ascii=False))

    state = extract_page_state(
        f'<script type="application/json" data-mfe-state="true">{escaped}</script>'
    )

    assert state is not None
    assert state.items[0].title == "Тестовый телефон"
    assert state.items[0].price == 42_000


def test_extract_page_state_skips_malformed_candidate_before_valid_script() -> None:
    payload = {"loaderData": {"data": {**_metadata(), "catalog": _catalog()}}}
    source = (
        '<script data-mfe-state="true">{"loaderData": malformed}</script>'
        + _script(payload, 'data-mfe-state="true" type="application/json"')
    )

    state = extract_page_state(source)

    assert state is not None
    assert state.context == "offline-context"
    assert state.items[0].id == "9876543210"


@pytest.mark.parametrize(
    "payload",
    [
        {"loaderData": {"data": {**_metadata(), "catalog": _catalog(1000000001)}}},
        {
            "loaderData": {
                "data": {**_metadata(), "result": {"catalog": _catalog(1000000002)}}
            }
        },
        {
            "loaderData": {
                "result": {**_metadata(), "catalog": _catalog(1000000003)}
            }
        },
        {"result": {**_metadata(), "catalog": _catalog(1000000004)}},
        {**_metadata(), "data": {"result": {"catalog": _catalog(1000000005)}}},
    ],
)
def test_extract_page_state_supports_bounded_catalog_wrapper_variants(
    payload: dict[str, object],
) -> None:
    state = extract_page_state(_script(payload))

    assert state is not None
    assert len(state.items) == 1
    assert state.context == "offline-context"
    assert state.api_params["categoryId"] == "99"


def test_extract_page_state_requires_enabled_mfe_marker() -> None:
    payload = {"loaderData": {"data": {**_metadata(), "catalog": _catalog()}}}
    source = (
        _script(payload, 'type="application/json"')
        + _script(payload, 'data-mfe-state="false"')
    )

    assert extract_page_state(source) is None


def test_extract_page_state_keeps_raw_catalog_count_when_items_are_unknown() -> None:
    payload = {
        "loaderData": {
            "data": {
                **_metadata(),
                "catalog": {"items": [{"unexpected": "new-schema"}]},
            }
        }
    }

    state = extract_page_state(_script(payload))

    assert state is not None
    assert state.items == ()
    assert state.catalog_item_count == 1
