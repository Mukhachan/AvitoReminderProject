import asyncio

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
    async def search(self, _: str) -> list[AvitoItem]:
        return [
            AvitoItem(
                id="1234567890",
                title="Новый телефон",
                price=40_000,
                url="https://www.avito.ru/moskva/telefony/telefon_1234567890",
            )
        ]


class BlockedClient:
    def __init__(self, diagnostic_path) -> None:
        self.diagnostic_path = diagnostic_path

    async def search(self, _: str) -> list[AvitoItem]:
        raise AvitoBlockedError(
            "Chromium получил от Avito HTTP 403",
            diagnostic_path=self.diagnostic_path,
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


def test_monitor_sends_avito_error_screenshot(tmp_path) -> None:
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
        assert len(bot.photos) == 1
        assert bot.photos[0][0] == search.chat_id
        assert "ошибке поиска #1" in bot.photos[0][2]

    asyncio.run(scenario())
