import asyncio
from datetime import datetime

from avito_reminder.avito import AvitoBlockedError
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
    async def search(self, _: str, **_kwargs: object) -> list[AvitoItem]:
        return [
            AvitoItem(
                id="1234567890",
                title="Новый телефон",
                price=40_000,
                url="https://www.avito.ru/moskva/telefony/telefon_1234567890",
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
        assert len(bot.messages) == 1
        assert "Новый телефон" in bot.messages[0][1]

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
