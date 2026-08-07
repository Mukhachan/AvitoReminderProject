from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from .avito import AvitoClient, AvitoError, build_search_url
from .config import load_settings
from .database import Database
from .telegram_transport import create_telegram_session


def _probe_tcp(host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=3):
        pass


async def _telegram_check(settings) -> int:
    if settings.telegram_proxy:
        parsed = urlsplit(settings.telegram_proxy)
        assert parsed.hostname is not None and parsed.port is not None
        try:
            await asyncio.to_thread(_probe_tcp, parsed.hostname, parsed.port)
        except OSError as exc:
            print(
                "Telegram proxy: FAIL - "
                f"{parsed.hostname}:{parsed.port} недоступен ({type(exc).__name__})"
            )
            return 3
        print(f"Telegram proxy: OK - {parsed.scheme}://{parsed.hostname}:{parsed.port}")
    else:
        print("Telegram proxy: disabled, using direct connection")

    bot = Bot(settings.bot_token, session=create_telegram_session(settings, timeout=20))
    try:
        me = await bot.get_me()
        webhook = await bot.get_webhook_info()
    except TelegramAPIError as exc:
        print(f"Telegram API: FAIL - {type(exc).__name__}: {exc}")
        return 3
    finally:
        await bot.session.close()
    print(f"Telegram API: OK - @{me.username}")
    print("Telegram webhook:", "configured" if webhook.url else "empty (polling mode)")
    return 0


async def doctor(live: bool, telegram: bool, query: str, city: str) -> int:
    settings = load_settings(require_bot_token=telegram)
    print("Python:", sys.version.split()[0])
    print("Telegram token:", "configured" if settings.bot_token else "missing")
    print("Database:", settings.database_path)
    database = Database(settings.database_path)
    await database.initialize()
    print("Database check: OK")
    status = 0
    if telegram:
        status = max(status, await _telegram_check(settings))
    else:
        print("Telegram live check: skipped (use --telegram)")
    if not live:
        print("Avito live check: skipped (use --live)")
        return status

    url = build_search_url(query, city)
    async with AvitoClient(settings) as client:
        try:
            items = await client.search(url)
        except AvitoError as exc:
            if client.last_route:
                print("Avito last route:", client.last_route)
            print("Avito live check: FAIL -", exc)
            return max(status, 2)
    print("Avito route:", client.last_route)
    print(f"Avito live check: OK, parsed {len(items)} items")
    for item in items[:3]:
        print(f"- {item.id}: {item.title} ({item.url})")
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Avito Reminder diagnostics")
    parser.add_argument("--live", action="store_true", help="perform a live Avito request")
    parser.add_argument(
        "--telegram", action="store_true", help="check the Telegram API using TELEGRAM_PROXY"
    )
    parser.add_argument("--all", action="store_true", help="check Telegram and Avito")
    parser.add_argument("--query", default="iPhone 13")
    parser.add_argument("--city", default="Москва")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            doctor(
                live=args.live or args.all,
                telegram=args.telegram or args.all,
                query=args.query,
                city=args.city,
            )
        )
    )


if __name__ == "__main__":
    main()
