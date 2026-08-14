import asyncio
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.async_api import Route

from avito_reminder.avito import (
    AVITO_HOME_PAGE_NAME,
    AvitoBlockedError,
    AvitoCaptchaRequiredError,
    AvitoClient,
    AvitoParseError,
)

from .helpers import settings

HOME_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Avito</title></head>
  <body>
    <a data-marker="header/logo" href="/">Avito</a>
    <form>
      <input data-marker="search-form/suggest/input" placeholder="Поиск по объявлениям">
      <button data-marker="search-form/submit-button">Найти</button>
    </form>
    <nav>
      <a>Авто</a><a>Недвижимость</a><a>Услуги</a><a>Электроника</a>
    </nav>
  </body>
</html>
"""

DELAYED_HOME_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Delayed home — Avito</title></head>
  <body>
    <main id="home-shell">Загрузка главной страницы…</main>
    <script>
      window.setTimeout(() => {
        document.getElementById("home-shell").outerHTML = `
          <main>
            <input data-marker="search-form/suggest/input"
                   placeholder="Поиск по объявлениям">
            <button data-marker="search-form/submit-button">Найти</button>
            <nav>
              <a>Авто</a><a>Недвижимость</a><a>Услуги</a><a>Электроника</a>
            </nav>
          </main>`;
      }, 150);
    </script>
  </body>
</html>
"""

DELAYED_CAPTCHA_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Delayed challenge — Avito</title></head>
  <body>
    <main id="challenge-shell">Загрузка…</main>
    <script>
      window.setTimeout(() => {
        const text = "Продолжить для решения " + "капчи";
        document.getElementById("challenge-shell").innerHTML = `<p>${text}</p>`;
      }, 150);
    </script>
  </body>
</html>
"""

SEARCH_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>integration test — Avito</title></head>
  <body>
    <div hidden aria-hidden="true">Доступ ограничен: проблема с IP</div>
    <main data-marker="catalog-serp">
      <div data-marker="item" data-item-id="9876543210" itemtype="http://schema.org/Product">
        <a data-marker="item-title"
           href="/moskva/telefony/integration_phone_9876543210">
          <h3>Интеграционный телефон</h3>
        </a>
        <p data-marker="item-price">
          <meta itemprop="price" content="42000">42 000 ₽
        </p>
        <div data-marker="item-address">Москва, Тверская</div>
      </div>
    </main>
  </body>
</html>
"""

TRANSIENT_IP_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Проблема с IP</title></head>
  <body>
    <h2>Доступ ограничен: проблема с IP</h2>
    <p>Подождите немного и обновите страницу.</p>
    <script>window.location.hash = "block";</script>
  </body>
</html>
"""

SEARCH_SHELL_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Поиск — Avito</title></head>
  <body>
    <main id="search-shell" data-marker="catalog-serp" aria-busy="true">
      <div class="skeleton">Загрузка объявлений…</div>
    </main>
  </body>
</html>
"""

DELAYED_BLOCK_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Search shell — Avito</title></head>
  <body>
    <main id="search-shell" data-marker="catalog-serp" aria-busy="true">
      Загрузка объявлений…
    </main>
    <script>
      window.setTimeout(() => {
        document.getElementById("search-shell").outerHTML =
          `<main><h2>Блокировка IP</h2></main>`;
      }, 150);
    </script>
  </body>
</html>
"""

DELAYED_SEARCH_HTML = """
<!doctype html>
<html lang="ru">
  <head><meta charset="utf-8"><title>Delayed search — Avito</title></head>
  <body>
    <main id="search-shell" data-marker="catalog-serp" aria-busy="true">
      Загрузка объявлений…
    </main>
    <script>
      window.setTimeout(() => {
        document.getElementById("search-shell").outerHTML = `
          <main data-marker="catalog-serp" data-hydrated="true">
            <div data-marker="item" data-item-id="1122334455"
                 itemtype="http://schema.org/Product">
              <a data-marker="item-title"
                 href="/moskva/telefony/delayed_phone_1122334455">
                <h3>Телефон после гидратации</h3>
              </a>
              <p data-marker="item-price">
                <meta itemprop="price" content="51000">51 000 ₽
              </p>
              <div data-marker="item-address">Москва, Сокол</div>
            </div>
          </main>`;
      }, 150);
    </script>
  </body>
</html>
"""


def test_browser_search_flow_ignores_hidden_stale_ip_block_marker(tmp_path) -> None:
    target_url = "https://www.avito.ru/moskva?q=integration-test&s=104"
    document_urls: list[str] = []
    unexpected_urls: list[str] = []

    client = AvitoClient(
        settings(
            tmp_path / "integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_new_user_per_session=False,
            avito_identity_rotate_on_browser_start=False,
            avito_proxy_rotate_on_browser_start=False,
            avito_min_request_interval_seconds=1,
            avito_request_jitter_seconds=0,
            avito_page_reload_delay_seconds=1,
            avito_page_reload_jitter_seconds=0,
            avito_error_reload_attempts=1,
            request_retries=1,
        )
    )

    async def scenario():
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None

        async def fulfill_avito(route: Route) -> None:
            request = route.request
            parsed = urlsplit(request.url)
            if parsed.hostname != "www.avito.ru":
                unexpected_urls.append(request.url)
                await route.abort()
                return

            if request.resource_type != "document":
                await route.fulfill(status=204, body="")
                return

            document_urls.append(request.url)
            query = parse_qs(parsed.query)
            if parsed.path == "/" and not query:
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=HOME_HTML,
                )
                return
            if parsed.path == "/moskva" and query.get("q") == ["integration-test"]:
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=SEARCH_HTML,
                )
                return
            await route.fulfill(status=404, content_type="text/plain", body="unexpected route")

        await client._browser_context.route("**/*", fulfill_avito)
        try:
            return await client.search(target_url)
        finally:
            await client.close()

    items = asyncio.run(scenario())

    assert unexpected_urls == []
    assert document_urls == ["https://www.avito.ru/", target_url]
    assert len(items) == 1
    assert items[0].id == "9876543210"
    assert items[0].title == "Интеграционный телефон"
    assert items[0].price == 42_000
    assert items[0].location == "Москва, Тверская"
    assert items[0].url == (
        "https://www.avito.ru/moskva/telefony/integration_phone_9876543210"
    )


def test_delayed_home_dom_is_ready_before_search_navigation(tmp_path) -> None:
    target_url = "https://www.avito.ru/moskva?q=delayed-home&s=104"
    home_fulfilled_at: float | None = None
    search_requested_after: float | None = None
    client = AvitoClient(
        settings(
            tmp_path / "delayed-home-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_new_user_per_session=False,
            avito_identity_rotate_on_browser_start=False,
            avito_proxy_rotate_on_browser_start=False,
            avito_min_request_interval_seconds=0,
            avito_request_jitter_seconds=0,
            request_retries=1,
        )
    )

    async def scenario():
        nonlocal home_fulfilled_at, search_requested_after
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None

        async def fulfill_avito(route: Route) -> None:
            nonlocal home_fulfilled_at, search_requested_after
            request = route.request
            parsed = urlsplit(request.url)
            if parsed.hostname != "www.avito.ru":
                await route.abort()
                return
            if request.resource_type != "document":
                await route.fulfill(status=204, body="")
                return
            if parsed.path == "/":
                home_fulfilled_at = time.monotonic()
                body = DELAYED_HOME_HTML
            elif parsed.path == "/moskva":
                assert home_fulfilled_at is not None
                search_requested_after = time.monotonic() - home_fulfilled_at
                body = SEARCH_HTML
            else:
                await route.fulfill(status=404, body="unexpected route")
                return
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=body,
            )

        await client._browser_context.route("**/*", fulfill_avito)
        try:
            return await client.search(target_url)
        finally:
            await client.close()

    items = asyncio.run(scenario())

    assert [item.id for item in items] == ["9876543210"]
    assert search_requested_after is not None
    assert search_requested_after >= 0.1


def test_unknown_successful_home_dom_is_not_retried_as_network_failure(tmp_path) -> None:
    target_url = "https://www.avito.ru/moskva?q=unknown-home&s=104"
    home_requests = 0
    client = AvitoClient(
        settings(
            tmp_path / "unknown-home-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_new_user_per_session=False,
            avito_identity_rotate_on_browser_start=False,
            avito_proxy_rotate_on_browser_start=False,
            avito_min_request_interval_seconds=0,
            avito_request_jitter_seconds=0,
            request_timeout_seconds=1,
            request_retries=3,
        )
    )

    async def scenario() -> None:
        nonlocal home_requests
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None

        async def fulfill_unknown_home(route: Route) -> None:
            nonlocal home_requests
            if route.request.resource_type == "document":
                home_requests += 1
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body="<main><div>Unknown Avito redesign shell</div></main>",
                )
                return
            await route.fulfill(status=204, body="")

        await client._browser_context.route("**/*", fulfill_unknown_home)
        try:
            with pytest.raises(AvitoParseError, match="ожидаемый DOM"):
                await client.search(target_url)
        finally:
            await client.close()

    asyncio.run(scenario())

    assert home_requests == 1


def test_transient_ip_page_reloads_once_then_search_succeeds(tmp_path) -> None:
    target_url = "https://www.avito.ru/moskva?q=recovered&s=104"
    home_requests = 0
    search_requests = 0
    unexpected_urls: list[str] = []
    client = AvitoClient(
        settings(
            tmp_path / "transient-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_new_user_per_session=False,
            avito_identity_rotate_on_browser_start=False,
            avito_proxy_rotate_on_browser_start=False,
            avito_min_request_interval_seconds=0,
            avito_request_jitter_seconds=0,
            avito_page_reload_delay_seconds=0,
            avito_page_reload_jitter_seconds=0,
            avito_error_reload_attempts=1,
            request_retries=1,
        )
    )

    async def scenario():
        nonlocal home_requests, search_requests
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None

        async def fulfill_avito(route: Route) -> None:
            nonlocal home_requests, search_requests
            request = route.request
            parsed = urlsplit(request.url)
            if parsed.hostname != "www.avito.ru":
                unexpected_urls.append(request.url)
                await route.abort()
                return
            if request.resource_type != "document":
                await route.fulfill(status=204, body="")
                return
            query = parse_qs(parsed.query)
            if parsed.path == "/" and not query:
                home_requests += 1
                body = TRANSIENT_IP_HTML if home_requests == 1 else HOME_HTML
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=body,
                )
                return
            if parsed.path == "/moskva" and query.get("q") == ["recovered"]:
                search_requests += 1
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=SEARCH_HTML,
                )
                return
            await route.fulfill(status=404, content_type="text/plain", body="unexpected route")

        await client._browser_context.route("**/*", fulfill_avito)
        try:
            return await client.search(target_url)
        finally:
            await client.close()

    items = asyncio.run(scenario())

    assert unexpected_urls == []
    assert home_requests == 2
    assert search_requests == 1
    assert [item.id for item in items] == ["9876543210"]


@pytest.mark.parametrize(
    ("blocked_html", "expected_error", "status"),
    [
        (
            '<main><button data-marker="captcha">Нажмите для подтверждения</button></main>',
            AvitoCaptchaRequiredError,
            429,
        ),
        (
            "<main><h2>Блокировка IP</h2></main>",
            AvitoBlockedError,
            429,
        ),
    ],
)
def test_visible_captcha_or_hard_block_is_handled_without_reload(
    tmp_path,
    monkeypatch,
    blocked_html: str,
    expected_error: type[AvitoBlockedError],
    status: int,
) -> None:
    page_requests = 0
    notifications: list[AvitoBlockedError] = []
    client = AvitoClient(
        settings(
            tmp_path / "immediate-block-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_page_reload_delay_seconds=2,
            avito_page_reload_jitter_seconds=0,
        )
    )

    async def no_diagnostic(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client, "_save_browser_diagnostic", no_diagnostic)

    async def scenario() -> None:
        nonlocal page_requests
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None
        page = await client._acquire_browser_page()

        async def fulfill_block(route: Route) -> None:
            nonlocal page_requests
            request = route.request
            if request.resource_type == "document":
                page_requests += 1
                await route.fulfill(
                    status=status,
                    content_type="text/html; charset=utf-8",
                    body=blocked_html,
                )
                return
            await route.fulfill(status=204, body="")

        await client._browser_context.route("**/*", fulfill_block)
        try:
            response = await page.goto("https://www.avito.ru/", wait_until="domcontentloaded")
            assert response is not None
            html = await page.content()

            async def on_blocked(exc: AvitoBlockedError) -> None:
                notifications.append(exc)

            with pytest.raises(AvitoBlockedError):
                await asyncio.wait_for(
                    client._wait_then_reload_avito_page(
                        page,
                        status=response.status,
                        html=html,
                        page_name=AVITO_HOME_PAGE_NAME,
                        on_blocked=on_blocked,
                    ),
                    timeout=10,
                )
        finally:
            await client.close()

    asyncio.run(scenario())

    assert page_requests == 1
    assert len(notifications) == 1
    assert isinstance(notifications[0], expected_error)


def test_delayed_phrase_only_captcha_is_detected_without_full_timeout(
    tmp_path, monkeypatch
) -> None:
    notifications: list[AvitoBlockedError] = []
    client = AvitoClient(
        settings(
            tmp_path / "delayed-captcha-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_page_reload_delay_seconds=2,
            avito_page_reload_jitter_seconds=0,
            request_timeout_seconds=5,
        )
    )

    async def no_diagnostic(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client, "_save_browser_diagnostic", no_diagnostic)

    async def scenario() -> float:
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None
        page = await client._acquire_browser_page()

        async def fulfill_delayed_captcha(route: Route) -> None:
            if route.request.resource_type == "document":
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=DELAYED_CAPTCHA_HTML,
                )
                return
            await route.fulfill(status=204, body="")

        await client._browser_context.route("**/*", fulfill_delayed_captcha)
        try:
            response = await page.goto("https://www.avito.ru/", wait_until="domcontentloaded")
            assert response is not None
            html = await page.content()

            async def on_blocked(exc: AvitoBlockedError) -> None:
                notifications.append(exc)

            started = time.monotonic()
            with pytest.raises(AvitoBlockedError):
                await client._wait_then_reload_avito_page(
                    page,
                    status=response.status,
                    html=html,
                    page_name=AVITO_HOME_PAGE_NAME,
                    on_blocked=on_blocked,
                )
            return time.monotonic() - started
        finally:
            await client.close()

    elapsed = asyncio.run(scenario())

    assert elapsed < 1
    assert len(notifications) == 1
    assert isinstance(notifications[0], AvitoCaptchaRequiredError)


@pytest.mark.parametrize("target_body", [HOME_HTML, SEARCH_SHELL_HTML])
def test_target_url_page_shell_is_not_accepted_as_serp(tmp_path, target_body: str) -> None:
    target_url = "https://www.avito.ru/moskva?q=shell&s=104"
    document_urls: list[str] = []
    client = AvitoClient(
        settings(
            tmp_path / "search-shell-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_new_user_per_session=False,
            avito_identity_rotate_on_browser_start=False,
            avito_proxy_rotate_on_browser_start=False,
            avito_min_request_interval_seconds=0,
            avito_request_jitter_seconds=0,
            request_timeout_seconds=1,
            request_retries=1,
        )
    )

    async def scenario() -> None:
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None

        async def fulfill_shell(route: Route) -> None:
            request = route.request
            parsed = urlsplit(request.url)
            if parsed.hostname != "www.avito.ru":
                await route.abort()
                return
            if request.resource_type != "document":
                await route.fulfill(status=204, body="")
                return
            document_urls.append(request.url)
            body = HOME_HTML if parsed.path == "/" else target_body
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=body,
            )

        await client._browser_context.route("**/*", fulfill_shell)
        try:
            with pytest.raises(AvitoParseError):
                await client.search(target_url)
        finally:
            await client.close()

    asyncio.run(scenario())
    assert document_urls == ["https://www.avito.ru/", target_url]


def test_delayed_search_dom_is_accepted_and_parsed(tmp_path) -> None:
    target_url = "https://www.avito.ru/moskva?q=delayed&s=104"
    document_urls: list[str] = []
    client = AvitoClient(
        settings(
            tmp_path / "delayed-serp-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_new_user_per_session=False,
            avito_identity_rotate_on_browser_start=False,
            avito_proxy_rotate_on_browser_start=False,
            avito_min_request_interval_seconds=0,
            avito_request_jitter_seconds=0,
            request_retries=1,
        )
    )

    async def scenario():
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None

        async def fulfill_avito(route: Route) -> None:
            request = route.request
            parsed = urlsplit(request.url)
            if parsed.hostname != "www.avito.ru":
                await route.abort()
                return
            if request.resource_type != "document":
                await route.fulfill(status=204, body="")
                return
            document_urls.append(request.url)
            if parsed.path == "/":
                body = HOME_HTML
            elif parsed.path == "/moskva":
                body = DELAYED_SEARCH_HTML
            else:
                await route.fulfill(status=404, body="unexpected route")
                return
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=body,
            )

        await client._browser_context.route("**/*", fulfill_avito)
        try:
            return await client.search(target_url)
        finally:
            await client.close()

    items = asyncio.run(scenario())

    assert document_urls == ["https://www.avito.ru/", target_url]
    assert [item.id for item in items] == ["1122334455"]
    assert items[0].title == "Телефон после гидратации"


def test_delayed_hard_block_is_classified_before_search_parse(
    tmp_path,
    monkeypatch,
) -> None:
    target_url = "https://www.avito.ru/moskva?q=delayed-block&s=104"
    document_urls: list[str] = []
    notifications: list[AvitoBlockedError] = []
    client = AvitoClient(
        settings(
            tmp_path / "delayed-block-integration.db",
            avito_transport="browser",
            avito_browser_headless=True,
            avito_browser_snapshots=False,
            avito_log_public_ip=False,
            avito_new_user_per_session=False,
            avito_identity_rotate_on_browser_start=False,
            avito_proxy_rotate_on_browser_start=False,
            avito_min_request_interval_seconds=0,
            avito_request_jitter_seconds=0,
            request_timeout_seconds=2,
            request_retries=1,
        )
    )

    async def no_diagnostic(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client, "_save_browser_diagnostic", no_diagnostic)

    async def scenario() -> None:
        await client._start_browser()
        await client._start_browser_session()
        assert client._browser_context is not None

        async def fulfill_avito(route: Route) -> None:
            request = route.request
            parsed = urlsplit(request.url)
            if request.resource_type != "document":
                await route.fulfill(status=204, body="")
                return
            document_urls.append(request.url)
            body = HOME_HTML if parsed.path == "/" else DELAYED_BLOCK_HTML
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=body,
            )

        async def on_blocked(exc: AvitoBlockedError) -> None:
            notifications.append(exc)

        await client._browser_context.route("**/*", fulfill_avito)
        try:
            with pytest.raises(AvitoBlockedError):
                await client.search(target_url, on_blocked=on_blocked)
        finally:
            await client.close()

    asyncio.run(scenario())

    assert document_urls == ["https://www.avito.ru/", target_url]
    assert len(notifications) == 1
    assert client._route_health.quarantine_remaining(client._route_health_key()) > 0


def test_browser_storage_state_survives_restart_for_same_route_and_identity(tmp_path) -> None:
    profile = tmp_path / "profile"
    cfg = settings(
        tmp_path / "storage-integration.db",
        avito_transport="browser",
        avito_browser_profile_path=profile,
        avito_browser_stealth=False,
        avito_new_user_per_session=False,
        avito_identity_rotate_on_browser_start=False,
        avito_proxy_rotate_on_browser_start=False,
        avito_log_public_ip=False,
    )

    async def scenario() -> tuple[str | None, str | None]:
        first = AvitoClient(cfg)
        await first._start_browser()
        await first._start_browser_session()
        assert first._browser_context is not None
        await first._browser_context.add_cookies(
            [
                {
                    "name": "integration-session",
                    "value": "preserved",
                    "domain": ".avito.ru",
                    "path": "/",
                }
            ]
        )
        await first._save_browser_storage_state()
        storage_path = first._browser_storage_state_path()
        payload = json.loads(storage_path.read_text(encoding="utf-8"))
        saved_value = next(
            (
                cookie["value"]
                for cookie in payload["cookies"]
                if cookie["name"] == "integration-session"
            ),
            None,
        )
        await first.close()

        second = AvitoClient(cfg)
        await second._start_browser()
        await second._start_browser_session()
        assert second._browser_context is not None
        restored = await second._browser_context.cookies(["https://www.avito.ru/"])
        restored_value = next(
            (
                cookie["value"]
                for cookie in restored
                if cookie["name"] == "integration-session"
            ),
            None,
        )
        await second.close()
        return saved_value, restored_value

    assert asyncio.run(scenario()) == ("preserved", "preserved")


def test_browser_indexed_db_survives_restart_for_same_route_and_identity(tmp_path) -> None:
    profile = tmp_path / "indexed-db-profile"
    cfg = settings(
        tmp_path / "indexed-db-integration.db",
        avito_transport="browser",
        avito_browser_profile_path=profile,
        avito_browser_stealth=False,
        avito_new_user_per_session=False,
        avito_identity_rotate_on_browser_start=False,
        avito_proxy_rotate_on_browser_start=False,
        avito_log_public_ip=False,
    )

    async def install_local_avito_route(client: AvitoClient) -> None:
        assert client._browser_context is not None

        async def fulfill_storage_page(route: Route) -> None:
            request = route.request
            parsed = urlsplit(request.url)
            if (
                request.resource_type == "document"
                and parsed.hostname == "www.avito.ru"
                and parsed.path == "/storage-test"
            ):
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body="<!doctype html><title>storage test</title>",
                )
                return
            await route.fulfill(status=204, body="")

        await client._browser_context.route("**/*", fulfill_storage_page)

    async def write_marker(client: AvitoClient) -> None:
        assert client._browser_context is not None
        page = await client._browser_context.new_page()
        await page.goto(
            "https://www.avito.ru/storage-test",
            wait_until="domcontentloaded",
        )
        await page.evaluate(
            """
            () => new Promise((resolve, reject) => {
              const request = indexedDB.open("avito-reminder-integration", 1);
              request.onupgradeneeded = () => {
                request.result.createObjectStore("session");
              };
              request.onerror = () => reject(request.error);
              request.onsuccess = () => {
                const database = request.result;
                const transaction = database.transaction("session", "readwrite");
                transaction.objectStore("session").put("preserved", "identity");
                transaction.oncomplete = () => {
                  database.close();
                  resolve();
                };
                transaction.onerror = () => reject(transaction.error);
              };
            })
            """
        )
        await page.close()

    async def read_marker(client: AvitoClient) -> str | None:
        assert client._browser_context is not None
        page = await client._browser_context.new_page()
        await page.goto(
            "https://www.avito.ru/storage-test",
            wait_until="domcontentloaded",
        )
        value = await page.evaluate(
            """
            () => new Promise((resolve, reject) => {
              const request = indexedDB.open("avito-reminder-integration", 1);
              request.onerror = () => reject(request.error);
              request.onsuccess = () => {
                const database = request.result;
                if (!database.objectStoreNames.contains("session")) {
                  database.close();
                  resolve(null);
                  return;
                }
                const transaction = database.transaction("session", "readonly");
                const getRequest = transaction.objectStore("session").get("identity");
                getRequest.onsuccess = () => {
                  database.close();
                  resolve(getRequest.result ?? null);
                };
                getRequest.onerror = () => reject(getRequest.error);
              };
            })
            """
        )
        await page.close()
        return value

    async def scenario() -> tuple[bool, str | None]:
        first = AvitoClient(cfg)
        await first._start_browser()
        await first._start_browser_session()
        await install_local_avito_route(first)
        await write_marker(first)
        await first._save_browser_storage_state()
        storage_path = first._browser_storage_state_path()
        payload = json.loads(storage_path.read_text(encoding="utf-8"))
        saved_indexed_db = any(
            origin.get("indexedDB")
            for origin in payload.get("origins", [])
            if origin.get("origin") == "https://www.avito.ru"
        )
        await first.close()

        second = AvitoClient(cfg)
        await second._start_browser()
        await second._start_browser_session()
        await install_local_avito_route(second)
        restored_value = await read_marker(second)
        await second.close()
        return saved_indexed_db, restored_value

    assert asyncio.run(scenario()) == (True, "preserved")
