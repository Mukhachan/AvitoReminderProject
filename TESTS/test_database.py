import asyncio
import sqlite3

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

        assert await database.set_active(search.id, 100, False)
        paused = await database.get_search(search.id, 100)
        assert paused is not None and not paused.active
        assert await database.delete_search(search.id, 100)
        assert await database.get_search(search.id, 100) is None

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
