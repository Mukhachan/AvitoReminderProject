import asyncio
from types import SimpleNamespace

from avito_reminder.browser_identity import generate_browser_identity
from avito_reminder.browser_sessions import (
    BrowserIdentityManager,
    diff_browser_snapshots,
    storage_leaks,
)


class ContextStub:
    def __init__(self) -> None:
        self.headers = None
        self.scripts: list[str] = []
        self.closed = False
        self.page = SimpleNamespace()

    async def set_extra_http_headers(self, headers):
        self.headers = headers

    async def add_init_script(self, *, script):
        self.scripts.append(script)

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class BrowserStub:
    def __init__(self) -> None:
        self.contexts: list[ContextStub] = []
        self.options: list[dict[str, object]] = []

    async def new_context(self, **options):
        context = ContextStub()
        self.contexts.append(context)
        self.options.append(options)
        return context


def _identity():
    return generate_browser_identity(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        impersonate="chrome136",
        locale="ru-RU",
        timezone_id="Europe/Moscow",
    )


def test_manager_creates_and_closes_a_fresh_context_for_every_session() -> None:
    browser = BrowserStub()
    manager = BrowserIdentityManager(browser, stealth=True)  # type: ignore[arg-type]

    async def scenario() -> tuple[str, str]:
        async with manager.open_session(_identity()) as first:
            first_id = first.session_id
        async with manager.open_session(_identity()) as second:
            second_id = second.session_id
        return first_id, second_id

    first_id, second_id = asyncio.run(scenario())

    assert first_id != second_id
    assert len(browser.contexts) == 2
    assert browser.contexts[0] is not browser.contexts[1]
    assert all(context.closed for context in browser.contexts)
    assert all(context.scripts for context in browser.contexts)
    assert "storage_state" not in browser.options[0]


def test_snapshot_diff_reports_nested_paths() -> None:
    differences = diff_browser_snapshots(
        {"timezone": "Europe/Moscow", "viewport": {"width": 1920, "height": 1080}},
        {"timezone": "Europe/Moscow", "viewport": {"width": 1366, "height": 768}},
    )

    assert [difference["path"] for difference in differences] == [
        "viewport.height",
        "viewport.width",
    ]


def test_storage_leak_audit_detects_only_previous_session_markers() -> None:
    clean = {
        "localStorage": None,
        "sessionStorage": None,
        "indexedDB": [],
        "cacheStorage": ["unrelated"],
        "serviceWorkers": [],
    }
    leaked = {
        **clean,
        "localStorage": "USER_A",
        "cacheStorage": ["identity-test-cache"],
    }

    assert storage_leaks(clean, "identity-test") == []
    assert storage_leaks(leaked, "identity-test") == ["localStorage", "cacheStorage"]
