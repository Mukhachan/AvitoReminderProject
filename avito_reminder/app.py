from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .avito import AvitoClient
from .config import load_settings
from .database import Database
from .runtime_lock import RuntimeLock
from .service import MonitorService
from .telegram import BOT_COMMANDS, router
from .telegram_transport import create_telegram_session


async def run() -> None:
    settings = load_settings()
    runtime_lock = RuntimeLock(settings.database_path)
    runtime_lock.acquire()
    try:
        logging.basicConfig(
            level=getattr(logging, settings.log_level, logging.INFO),
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        database = Database(
            settings.database_path,
            schedule_spread_seconds=settings.search_schedule_spread_seconds,
            minimum_interval_seconds=settings.search_interval_seconds,
        )
        await database.initialize()

        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            session=create_telegram_session(settings),
        )
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(router)
        client = AvitoClient(settings)
        service = MonitorService(bot=bot, database=database, client=client, settings=settings)
        worker: asyncio.Task[None] | None = None

        try:
            # Do not touch Avito while Telegram is unavailable. Otherwise a restarting
            # service can repeatedly hit Avito without ever becoming usable to the owner.
            await bot.get_me()
            await bot.set_my_commands(BOT_COMMANDS)
            worker = asyncio.create_task(service.run(), name="avito-monitor")
            await dispatcher.start_polling(
                bot,
                database=database,
                service=service,
                settings=settings,
                allowed_updates=dispatcher.resolve_used_update_types(),
            )
        finally:
            service.stop()
            if worker is not None:
                try:
                    await asyncio.wait_for(worker, timeout=5)
                except TimeoutError:
                    worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker
            await client.close()
            # start_polling normally closes this session, but startup can fail during
            # get_me/set_my_commands before polling takes ownership of it.
            await bot.session.close()
    finally:
        runtime_lock.release()


def main() -> None:
    asyncio.run(run())
