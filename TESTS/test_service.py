import asyncio
from datetime import datetime

from avito_reminder.avito import AvitoBlockedError, AvitoCaptchaRequiredError
from avito_reminder.database import Database
from avito_reminder.models import AvitoItem
from avito_reminder.service import MonitorService
from TESTS.helpers import settings


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.photos: list[tuple[int, object, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: object) -> None:
        self.messages.append((chat_id, text))

    async def send_photo(self, chat_id: int, photo: object, caption: str, **_: object) -> None:
        self.photos.append((chat_id, photo, caption))


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.initial_values: list[bool] = []

    async def search(self, _: str, **kwargs: object) -> list[AvitoItem]:
        self.calls += 1
        self.initial_values.append(bool(kwargs.get("initial")))
        return [
            AvitoItem(
                id="1234567890",
                title="Новый телефон",
                price=40_000,
                url="https://www.avito.ru/moskva/telefony/telefon_1234567890",
                image_url="https://images.example.test/telefon.jpg",
            )
        ]


class BlockedClient:
    def __init__(self, diagnostic_path, retry_after_seconds: int | None = None) -> None:
        self.diagnostic_path = diagnostic_path
        self.retry_after_seconds = retry_after_seconds

    async def search(self, _: str, **_kwargs: object) -> list[AvitoItem]:
        raise AvitoBlockedError(
            "Chromium получил от Avito HTTP 403",
            diagnostic_path=self.diagnostic_path,
            retry_after_seconds=self.retry_after_seconds,
        )


def test_monitor_sends_new_item_once(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "service.db")
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=телефон",
        )
        bot = FakeBot()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=FakeClient(),  # type: ignore[arg-type]
            settings=cfg,
        )

        first = await service.check_search(search)
        assert (first.new, first.sent) == (1, 1)
        refreshed = await database.get_search(search.id, search.chat_id)
        assert refreshed is not None
        second = await service.check_search(refreshed)
        assert (second.new, second.sent) == (0, 0)
        assert bot.messages == []
        assert len(bot.photos) == 1
        assert bot.photos[0][1] == "https://images.example.test/telefon.jpg"
        assert "Новый телефон" in bot.photos[0][2]
        assert "Новое объявление по поиску" not in bot.photos[0][2]

    asyncio.run(scenario())


def test_monitor_postpones_search_for_cooldown_period(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "service.db")
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=телефон",
        )
        bot = FakeBot()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=BlockedClient(None, retry_after_seconds=10_800),  # type: ignore[arg-type]
            settings=cfg,
        )

        result = await service.check_search(search)
        updated = await database.get_search(search.id, search.chat_id)

        assert result.error is not None
        assert updated is not None and updated.last_checked_at is not None
        retry_delay = datetime.fromisoformat(updated.next_check_at) - datetime.fromisoformat(
            updated.last_checked_at
        )
        assert retry_delay.total_seconds() == 10_800
        assert any("на паузу" in text for _, text in bot.messages)

    asyncio.run(scenario())


def test_monitor_reports_avito_error_without_sending_screenshot(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "service.db")
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=телефон",
        )
        screenshot = tmp_path / "avito-403.png"
        screenshot.write_bytes(b"fake png")
        bot = FakeBot()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=BlockedClient(screenshot),  # type: ignore[arg-type]
            settings=cfg,
        )

        result = await service.check_search(search)

        assert result.error == "Chromium получил от Avito HTTP 403"
        assert len(bot.messages) == 1
        assert bot.photos == []

    asyncio.run(scenario())


def test_monitor_tells_user_to_complete_visible_captcha(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(
            tmp_path / "service.db",
            avito_browser_headless=False,
            avito_page_reload_delay_seconds=90,
            avito_page_reload_jitter_seconds=30,
        )
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="книги Мураками",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=мураками",
        )
        bot = FakeBot()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=FakeClient(),  # type: ignore[arg-type]
            settings=cfg,
        )

        await service._notify_avito_waiting(
            search,
            AvitoCaptchaRequiredError("Нажмите для подтверждения"),
        )

        assert len(bot.messages) == 1
        message = bot.messages[0][1]
        assert "Avito запросил проверку" in message
        assert "без ожидания" in message
        assert "смена IP недоступна" in message

    asyncio.run(scenario())


def test_monitor_reuses_cached_result_for_same_url(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "service.db", search_result_cache_seconds=600)
        database = Database(cfg.database_path)
        await database.initialize()
        first_search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=телефон",
        )
        second_search = await database.add_search(
            chat_id=11,
            user_id=21,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            url=first_search.url,
        )
        bot = FakeBot()
        client = FakeClient()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=client,  # type: ignore[arg-type]
            settings=cfg,
        )

        first, second = await asyncio.gather(
            service.check_search(first_search),
            service.check_search(second_search),
        )

        assert first.found == second.found == 1
        assert client.calls == 1
        assert client.initial_values == [True]

    asyncio.run(scenario())


def test_captcha_message_describes_single_rotation_when_pool_is_enabled(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(
            tmp_path / "service.db",
            avito_proxy_mode="proxy",
            avito_proxy_pool=("http://proxy.example.test:1000",),
            avito_proxy_rotation_enabled=True,
        )
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="книги",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=книги",
        )
        bot = FakeBot()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=FakeClient(),  # type: ignore[arg-type]
            settings=cfg,
        )

        await service._notify_avito_waiting(
            search,
            AvitoCaptchaRequiredError("Нажмите для подтверждения"),
        )

        assert "сменит пользователя и IP один раз" in bot.messages[0][1]

    asyncio.run(scenario())
