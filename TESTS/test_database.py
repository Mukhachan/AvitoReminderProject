import asyncio

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
        )
        assert (await database.get_search(search.id, 100)) == search

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
