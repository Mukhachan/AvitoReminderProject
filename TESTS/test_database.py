import asyncio
import sqlite3
from datetime import datetime, timedelta

from avito_reminder.database import Database
from avito_reminder.models import AvitoItem


def test_database_search_and_notification_lifecycle(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "test.db")
        await database.initialize()
        search = await database.add_search(
            chat_id=100,
            user_id=200,
            query="велосипед",
            city="Москва",
            price_min=10_000,
            price_max=50_000,
            url="https://www.avito.ru/moskva?q=велосипед",
            interval_seconds=1800,
        )
        assert (await database.get_search(search.id, 100)) == search
        assert search.interval_seconds == 1800

        item = AvitoItem("1234567890", "Велосипед", 25_000, "https://example.test/item")
        assert await database.record_items(search.id, [item], notify=True) == 1
        assert await database.record_items(search.id, [item], notify=True) == 0
        assert await database.pending_items(search.id, 5) == [item]

        await database.mark_notified(search.id, item.id)
        assert await database.pending_items(search.id, 5) == []
        await database.mark_success(search.id, 60)
        updated = await database.get_search(search.id, 100)
        assert updated is not None and updated.initialized and updated.last_error is None

        previous_next_check = updated.next_check_at
        assert await database.postpone_active_searches(10_800) == 1
        postponed = await database.get_search(search.id, 100)
        assert postponed is not None
        assert postponed.next_check_at > previous_next_check

        assert await database.set_active(search.id, 100, False)
        paused = await database.get_search(search.id, 100)
        assert paused is not None and not paused.active
        assert await database.delete_search(search.id, 100)
        assert await database.get_search(search.id, 100) is None

    asyncio.run(scenario())


def test_users_have_isolated_search_lists_and_permissions(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "user-isolation.db")
        await database.initialize()
        first = await database.add_search(
            chat_id=-100500,
            user_id=200,
            query="велосипед",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=велосипед",
        )
        second = await database.add_search(
            chat_id=-100500,
            user_id=201,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=телефон",
        )

        assert await database.list_user_searches(200) == [first]
        assert await database.list_user_searches(201) == [second]
        assert await database.get_user_search(second.id, 200) is None
        assert not await database.set_user_search_active(second.id, 200, False)
        assert not await database.delete_user_search(first.id, 201)

        assert await database.set_user_search_active(first.id, 200, False)
        paused = await database.get_user_search(first.id, 200)
        assert paused is not None and not paused.active
        assert await database.delete_user_search(first.id, 200)
        assert await database.list_user_searches(200) == []

        assert await database.deactivate_user_searches(201) == 1
        deactivated = await database.get_user_search(second.id, 201)
        assert deactivated is not None and not deactivated.active

    asyncio.run(scenario())


def test_pending_item_is_enriched_with_image_before_telegram_delivery(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "pending-image.db")
        await database.initialize()
        search = await database.add_search(
            chat_id=100,
            user_id=200,
            query="телефон",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=телефон",
        )
        without_image = AvitoItem(
            "1234567890",
            "Телефон",
            25_000,
            "https://www.avito.ru/item_1234567890",
        )
        with_image = AvitoItem(
            "1234567890",
            "Телефон",
            25_000,
            "https://www.avito.ru/item_1234567890",
            image_url="https://10.img.example.test/phone.jpg",
        )

        assert await database.record_items(search.id, [without_image], notify=True) == 1
        assert await database.record_items(search.id, [with_image], notify=True) == 0

        pending = await database.pending_items(search.id, 5)
        assert pending == [with_image]

    asyncio.run(scenario())


def test_database_migrates_existing_searches_with_default_interval(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                city TEXT NOT NULL,
                price_min INTEGER,
                price_max INTEGER,
                url TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                initialized INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_checked_at TEXT,
                next_check_at TEXT NOT NULL,
                last_error TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            INSERT INTO searches (
                chat_id, user_id, query, city, url, created_at, next_check_at
            ) VALUES (100, 200, 'телефон', 'Москва', 'https://www.avito.ru/moskva',
                      '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )

    async def scenario() -> None:
        database = Database(path)
        await database.initialize()
        search = await database.get_search(1, 100)
        assert search is not None
        assert search.interval_seconds == 900

    asyncio.run(scenario())


def test_database_raises_legacy_and_new_intervals_to_configured_minimum(tmp_path) -> None:
    path = tmp_path / "minimum.db"

    async def scenario() -> None:
        legacy_database = Database(path)
        await legacy_database.initialize()
        legacy = await legacy_database.add_search(
            chat_id=1,
            user_id=1,
            query="старый",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=old",
            interval_seconds=900,
        )
        assert legacy.interval_seconds == 900

        database = Database(path, minimum_interval_seconds=1800)
        await database.initialize()
        migrated = await database.get_search(legacy.id)
        created = await database.add_search(
            chat_id=2,
            user_id=2,
            query="новый",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=new",
            interval_seconds=900,
        )

        assert migrated is not None and migrated.interval_seconds == 1800
        assert created.interval_seconds == 1800

    asyncio.run(scenario())


def test_database_spreads_new_searches_deterministically(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "spread.db", schedule_spread_seconds=300)
        await database.initialize()
        first = await database.add_search(
            chat_id=100,
            user_id=200,
            query="велосипед",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=велосипед",
        )
        second = await database.add_search(
            chat_id=101,
            user_id=201,
            query="самокат",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=самокат",
        )

        assert first.next_check_at != second.next_check_at
        first_delay = datetime.fromisoformat(first.next_check_at) - datetime.fromisoformat(
            first.created_at
        )
        second_delay = datetime.fromisoformat(second.next_check_at) - datetime.fromisoformat(
            second.created_at
        )
        assert 0 <= first_delay.total_seconds() <= 300
        assert 0 <= second_delay.total_seconds() <= 300

    asyncio.run(scenario())


def test_database_keeps_schedule_spread_after_success(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "spread-success.db", schedule_spread_seconds=300)
        await database.initialize()
        first = await database.add_search(
            chat_id=100,
            user_id=200,
            query="велосипед",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=велосипед",
        )
        second = await database.add_search(
            chat_id=101,
            user_id=201,
            query="самокат",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=самокат",
        )

        await database.mark_success(first.id, 1800)
        await database.mark_success(second.id, 1800)
        first_updated = await database.get_search(first.id)
        second_updated = await database.get_search(second.id)

        assert first_updated is not None and second_updated is not None
        assert first_updated.next_check_at != second_updated.next_check_at

    asyncio.run(scenario())


def test_failure_does_not_shorten_existing_global_postpone(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "postpone.db", schedule_spread_seconds=300)
        await database.initialize()
        search = await database.add_search(
            chat_id=100,
            user_id=200,
            query="велосипед",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=велосипед",
        )

        await database.postpone_active_searches(10_800)
        postponed = await database.get_search(search.id)
        assert postponed is not None
        await database.mark_failure(search.id, "blocked", 10_800)
        failed = await database.get_search(search.id)

        assert failed is not None
        assert datetime.fromisoformat(failed.next_check_at) >= datetime.fromisoformat(
            postponed.next_check_at
        )

    asyncio.run(scenario())


def test_success_does_not_shorten_a_later_existing_schedule(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "success-postpone.db")
        await database.initialize()
        search = await database.add_search(
            chat_id=100,
            user_id=200,
            query="велосипед",
            city="Москва",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=велосипед",
        )

        await database.postpone_active_searches(10_800)
        postponed = await database.get_search(search.id)
        assert postponed is not None
        await database.mark_success(search.id, 1800)
        succeeded = await database.get_search(search.id)

        assert succeeded is not None
        assert datetime.fromisoformat(succeeded.next_check_at) >= datetime.fromisoformat(
            postponed.next_check_at
        ) - timedelta(seconds=1)

    asyncio.run(scenario())


def test_success_resets_an_old_search_specific_failure_backoff(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "success-resets-failure.db")
        await database.initialize()
        search = await database.add_search(
            chat_id=100,
            user_id=200,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=phone",
        )
        await database.mark_failure(search.id, "schema changed", 21_600)
        failed = await database.get_search(search.id)
        assert failed is not None

        before_success = datetime.now().astimezone()
        await database.mark_success(search.id, 1800)
        succeeded = await database.get_search(search.id)

        assert succeeded is not None
        assert succeeded.failure_count == 0
        assert succeeded.last_error is None
        succeeded_at = datetime.fromisoformat(succeeded.next_check_at)
        assert before_success + timedelta(seconds=1790) <= succeeded_at
        assert succeeded_at < datetime.fromisoformat(failed.next_check_at)

    asyncio.run(scenario())


def test_global_avito_cooldown_survives_restart_and_covers_add_resume_and_due(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "global-cooldown.db"
        database = Database(path)
        await database.initialize()
        existing = await database.add_search(
            chat_id=100,
            user_id=200,
            query="existing",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=existing",
        )
        await database.postpone_active_searches(3600)

        restarted = Database(path)
        await restarted.initialize()
        assert await restarted.avito_retry_after_seconds() > 3500
        assert await restarted.due_searches() == []

        created = await restarted.add_search(
            chat_id=101,
            user_id=201,
            query="created",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=created",
        )
        await restarted.set_active(existing.id, existing.chat_id, False)
        await restarted.set_active(existing.id, existing.chat_id, True)
        resumed = await restarted.get_search(existing.id)

        assert resumed is not None
        assert datetime.fromisoformat(created.next_check_at) > datetime.now().astimezone()
        assert datetime.fromisoformat(resumed.next_check_at) > datetime.now().astimezone()
        assert await restarted.due_searches() == []

    asyncio.run(scenario())


def test_pending_searches_are_available_without_becoming_due_for_avito(tmp_path) -> None:
    async def scenario() -> None:
        database = Database(tmp_path / "pending-outbox.db")
        await database.initialize()
        search = await database.add_search(
            chat_id=100,
            user_id=200,
            query="phone",
            city="Moscow",
            price_min=None,
            price_max=None,
            url="https://www.avito.ru/moskva?q=phone",
            interval_seconds=7200,
        )
        item = AvitoItem("1", "Phone", 1, "https://example.test/1")
        await database.record_items(search.id, [item], notify=True)
        await database.mark_success(search.id, 7200)

        pending = await database.searches_with_pending_items()

        assert [candidate.id for candidate in pending] == [search.id]
        assert await database.due_searches() == []

    asyncio.run(scenario())
