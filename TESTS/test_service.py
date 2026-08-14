import asyncio
from datetime import datetime

from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from avito_reminder.avito import (
    AvitoBlockedError,
    AvitoCaptchaRequiredError,
    AvitoHardBlockedError,
    AvitoParseError,
)
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


class CountingBlockedClient(BlockedClient):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(None, retry_after_seconds)
        self.calls = 0

    async def search(self, url: str, **kwargs: object) -> list[AvitoItem]:
        self.calls += 1
        return await super().search(url, **kwargs)


class ParseErrorClient:
    async def search(self, _: str, **_kwargs: object) -> list[AvitoItem]:
        raise AvitoParseError("неизвестный формат выдачи")


class FailingDeliveryBot(FakeBot):
    async def send_photo(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("telegram unavailable")


class RecoveringDeliveryBot(FakeBot):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    async def send_photo(self, *args: object, **kwargs: object) -> None:
        if self.fail:
            raise RuntimeError("telegram unavailable")
        await super().send_photo(*args, **kwargs)  # type: ignore[arg-type]


class ConcurrentClient:
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0

    async def search(self, _url: str, **_kwargs: object) -> list[AvitoItem]:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0.02)
            return []
        finally:
            self.active -= 1


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
        assert bot.messages == []

    asyncio.run(scenario())


def test_monitor_keeps_avito_error_internal(tmp_path) -> None:
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
        assert bot.messages == []
        assert bot.photos == []

    asyncio.run(scenario())


def test_monitor_keeps_visible_captcha_internal(tmp_path) -> None:
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

        assert bot.messages == []

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


def test_captcha_with_proxy_rotation_sends_no_technical_message(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(
            tmp_path / "service.db",
            avito_proxy_mode="proxy",
            avito_proxy_pool=(
                "http://first.proxy.example.test:1000",
                "http://second.proxy.example.test:1000",
            ),
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

        assert bot.messages == []

    asyncio.run(scenario())


def test_captcha_with_fallback_proxy_sends_no_technical_message(
    tmp_path,
) -> None:
    async def scenario() -> None:
        cfg = settings(
            tmp_path / "service.db",
            avito_proxy_mode="fallback",
            avito_proxy_pool=("http://proxy.example.test:1000",),
            avito_proxy_rotation_enabled=True,
        )
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=phone",
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
            AvitoCaptchaRequiredError("captcha"),
        )

        assert bot.messages == []

    asyncio.run(scenario())


def test_telegram_rate_limit_does_not_delay_avito_block_handling(tmp_path) -> None:
    class RateLimitedBot:
        async def send_message(self, chat_id: int, text: str, **_: object) -> None:
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=chat_id, text=text),
                message="retry later",
                retry_after=300,
            )

    async def scenario() -> None:
        cfg = settings(tmp_path / "service.db")
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=phone",
        )
        service = MonitorService(
            bot=RateLimitedBot(),  # type: ignore[arg-type]
            database=database,
            client=FakeClient(),  # type: ignore[arg-type]
            settings=cfg,
        )

        await asyncio.wait_for(
            service._notify_avito_waiting(
                search,
                AvitoCaptchaRequiredError("captcha"),
            ),
            timeout=0.5,
        )

    asyncio.run(scenario())


def test_hard_ip_block_sends_no_technical_message(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "service.db")
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=phone",
        )
        bot = FakeBot()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=FakeClient(),  # type: ignore[arg-type]
            settings=cfg,
        )
        error = AvitoHardBlockedError("hard block")
        error.rotation_planned = True

        await service._notify_avito_waiting(search, error)

        assert bot.messages == []

    asyncio.run(scenario())


def test_hard_ip_block_without_rotation_hint_sends_no_technical_message(
    tmp_path,
) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "service.db")
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=phone",
        )
        bot = FakeBot()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=FakeClient(),  # type: ignore[arg-type]
            settings=cfg,
        )

        await service._notify_avito_waiting(search, AvitoHardBlockedError("hard block"))

        assert bot.messages == []

    asyncio.run(scenario())


def test_parse_error_uses_long_circuit_breaker(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "parse-error.db")
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
        service = MonitorService(
            bot=FakeBot(),  # type: ignore[arg-type]
            database=database,
            client=ParseErrorClient(),  # type: ignore[arg-type]
            settings=cfg,
        )

        await service.check_search(search)
        updated = await database.get_search(search.id, search.chat_id)

        assert updated is not None and updated.last_checked_at is not None
        retry_delay = datetime.fromisoformat(updated.next_check_at) - datetime.fromisoformat(
            updated.last_checked_at
        )
        assert retry_delay.total_seconds() == 3600

    asyncio.run(scenario())


def test_telegram_delivery_failure_keeps_regular_avito_schedule(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "delivery.db", search_interval_seconds=1800)
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            interval_seconds=1800,
            url="https://www.avito.ru/moskva?q=телефон",
        )
        service = MonitorService(
            bot=FailingDeliveryBot(),  # type: ignore[arg-type]
            database=database,
            client=FakeClient(),  # type: ignore[arg-type]
            settings=cfg,
        )

        result = await service.check_search(search)
        updated = await database.get_search(search.id, search.chat_id)
        pending = await database.pending_items(search.id, 5)

        assert result.error == "Объявления сохранены; отправка уведомлений будет повторена"
        assert updated is not None and updated.initialized
        assert updated.failure_count == 0
        assert updated.last_error is None
        assert updated.last_checked_at is not None
        retry_delay = datetime.fromisoformat(updated.next_check_at) - datetime.fromisoformat(
            updated.last_checked_at
        )
        assert retry_delay.total_seconds() == 1800
        assert [item.id for item in pending] == ["1234567890"]

    asyncio.run(scenario())


def test_monitor_serializes_avito_workflows_for_different_searches(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "concurrency.db")
        database = Database(cfg.database_path)
        await database.initialize()
        searches = [
            await database.add_search(
                chat_id=10 + index,
                user_id=20 + index,
                query=f"товар {index}",
                city="Москва",
                price_min=None,
                price_max=None,
                url=f"https://www.avito.ru/moskva?q=товар{index}",
            )
            for index in range(2)
        ]
        client = ConcurrentClient()
        service = MonitorService(
            bot=FakeBot(),  # type: ignore[arg-type]
            database=database,
            client=client,  # type: ignore[arg-type]
            settings=cfg,
        )

        await asyncio.gather(*(service.check_search(search) for search in searches))

        assert client.maximum_active == 1

    asyncio.run(scenario())


def test_pending_telegram_retry_does_not_fetch_avito_again(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "delivery-retry.db", search_interval_seconds=1800)
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            interval_seconds=1800,
            url="https://www.avito.ru/moskva?q=phone",
        )
        bot = RecoveringDeliveryBot()
        client = FakeClient()
        service = MonitorService(
            bot=bot,  # type: ignore[arg-type]
            database=database,
            client=client,  # type: ignore[arg-type]
            settings=cfg,
        )

        failed = await service.check_search(search)
        assert failed.error is not None
        assert client.calls == 1

        bot.fail = False
        await database.clear_pending_delivery_retry(search.id)
        await service._retry_pending_deliveries()

        assert client.calls == 1
        assert len(bot.photos) == 1
        assert await database.pending_items(search.id, 5) == []

    asyncio.run(scenario())


def test_manual_check_honours_persisted_global_cooldown(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "manual-cooldown.db")
        database = Database(cfg.database_path)
        await database.initialize()
        search = await database.add_search(
            chat_id=10,
            user_id=20,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=phone",
        )
        await database.postpone_active_searches(3600)
        client = FakeClient()
        service = MonitorService(
            bot=FakeBot(),  # type: ignore[arg-type]
            database=database,
            client=client,  # type: ignore[arg-type]
            settings=cfg,
        )

        result = await service.check_search(search)

        assert result.error is not None and "cooldown" in result.error
        assert client.calls == 0

    asyncio.run(scenario())


def test_simultaneous_checks_cannot_enter_before_block_cooldown_is_saved(tmp_path) -> None:
    async def scenario() -> None:
        cfg = settings(tmp_path / "concurrent-cooldown.db")
        database = Database(cfg.database_path)
        await database.initialize()
        searches = [
            await database.add_search(
                chat_id=10 + index,
                user_id=20 + index,
                query=f"phone {index}",
                city="Moscow",
                price_min=None,
                price_max=None,
                url=f"https://www.avito.ru/moskva?q=phone{index}",
            )
            for index in range(2)
        ]
        client = CountingBlockedClient(retry_after_seconds=3600)
        service = MonitorService(
            bot=FakeBot(),  # type: ignore[arg-type]
            database=database,
            client=client,  # type: ignore[arg-type]
            settings=cfg,
        )

        results = await asyncio.gather(
            *(service.check_search(search) for search in searches)
        )

        assert client.calls == 1
        assert all(result.error is not None for result in results)
        assert await database.avito_retry_after_seconds() > 3500

    asyncio.run(scenario())
