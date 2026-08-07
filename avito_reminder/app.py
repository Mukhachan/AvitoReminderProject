from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .avito import AvitoClient
from .config import load_settings
from .database import Database
from .service import MonitorService
from .telegram import BOT_COMMANDS, router
from .telegram_transport import create_telegram_session


async def run() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    database = Database(settings.database_path)
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
    worker = asyncio.create_task(service.run(), name="avito-monitor")

    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await dispatcher.start_polling(
            bot,
            database=database,
            service=service,
            settings=settings,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        service.stop()
        await worker
        await client.close()


def main() -> None:
    asyncio.run(run())
