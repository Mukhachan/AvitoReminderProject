from __future__ import annotations

import asyncio
import html
import logging
import time
from contextlib import suppress
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)

from .avito import (
    AvitoBlockedError,
    AvitoClient,
    AvitoError,
    AvitoParseError,
)
from .config import Settings
from .database import Database
from .models import AvitoItem, Search

logger = logging.getLogger(__name__)

PENDING_DELIVERY_RETRY_SECONDS = 5 * 60


@dataclass(frozen=True, slots=True)
class CheckResult:
    found: int
    new: int
    sent: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _CachedSearchResult:
    expires_at: float
    items: tuple[AvitoItem, ...]


def format_price(price: int | None) -> str:
    return "Цена не указана" if price is None else f"{price:,} ₽".replace(",", " ")


def item_message(search: Search, item: AvitoItem) -> str:
    parts = [
        f"<b>{html.escape(item.title)}</b>",
        html.escape(format_price(item.price)),
    ]
    if item.location:
        parts.append(f"📍 {html.escape(item.location)}")
    parts.append(f"Поиск: {html.escape(search.query)} · {html.escape(search.city)}")
    return "\n".join(parts)


class MonitorService:
    def __init__(self, *, bot: Bot, database: Database, client: AvitoClient, settings: Settings):
        self.bot = bot
        self.database = database
        self.client = client
        self.settings = settings
        self._stop = asyncio.Event()
        self._locks: dict[int, asyncio.Lock] = {}
        # One outbound Avito workflow at a time. Browser mode already serializes in
        # AvitoClient; applying the same rule here also protects HTTP mode and shared IPs.
        self._semaphore = asyncio.Semaphore(1)
        self._search_cache: dict[str, _CachedSearchResult] = {}
        self._url_locks: dict[str, asyncio.Lock] = {}

    async def _search_items(self, search: Search, *, on_blocked) -> list[AvitoItem]:
        lock = self._url_locks.setdefault(search.url, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            cached = self._search_cache.get(search.url)
            if cached is not None and cached.expires_at > now:
                logger.info(
                    "Поиск #%s использует общий кэш URL: осталось %.1f с",
                    search.id,
                    cached.expires_at - now,
                )
                return list(cached.items)
            if cached is not None:
                self._search_cache.pop(search.url, None)

            items = await self.client.search(
                search.url,
                on_blocked=on_blocked,
                initial=not search.initialized,
            )
            if self.settings.search_result_cache_seconds:
                self._search_cache[search.url] = _CachedSearchResult(
                    expires_at=time.monotonic() + self.settings.search_result_cache_seconds,
                    items=tuple(items),
                )
            return items

    async def run(self) -> None:
        logger.info("Мониторинг Avito запущен")
        delivery_worker = asyncio.create_task(
            self._run_delivery_loop(), name="telegram-pending-delivery"
        )
        try:
            while not self._stop.is_set():
                try:
                    # Claim only one current row per scheduler pass. A large ``gather``
                    # snapshot keeps stale jobs queued after another job has activated a
                    # global cooldown; one-at-a-time processing lets the next pass observe
                    # the updated ``next_check_at`` values first.
                    searches = await self.database.due_searches(limit=1)
                    if searches:
                        result = await self.check_search(searches[0])
                        # Re-read the database immediately. The Avito client owns the
                        # request pacing; an extra scheduler_poll delay only slows a safe
                        # queue and prevents cached identical URLs from being fanned out.
                        if result.error != "Проверка уже выполняется":
                            continue
                except Exception:
                    logger.exception("Ошибка цикла мониторинга")
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.scheduler_poll_seconds
                    )
        finally:
            delivery_worker.cancel()
            with suppress(asyncio.CancelledError):
                await delivery_worker
        logger.info("Мониторинг Avito остановлен")

    async def _run_delivery_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._retry_pending_deliveries()
            except Exception:
                logger.exception("Ошибка цикла доставки уведомлений Telegram")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.scheduler_poll_seconds
                )

    def stop(self) -> None:
        self._stop.set()

    async def check_search(self, search: Search) -> CheckResult:
        lock = self._locks.setdefault(search.id, asyncio.Lock())
        if lock.locked():
            return CheckResult(found=0, new=0, sent=0, error="Проверка уже выполняется")
        async with lock:
            async def notify_blocked(exc: AvitoBlockedError) -> None:
                await self._notify_avito_waiting(search, exc)

            async with self._semaphore:
                try:
                    retry_after = await self.database.avito_retry_after_seconds()
                    if retry_after:
                        await self.database.mark_failure(
                            search.id,
                            "Global Avito cooldown is still active",
                            retry_after,
                        )
                        return CheckResult(
                            0,
                            0,
                            0,
                            f"Avito cooldown is active for {retry_after} more seconds",
                        )
                    items = await self._search_items(search, on_blocked=notify_blocked)
                    should_notify = search.initialized or self.settings.notify_initial_results
                    new_count = await self.database.record_items(
                        search.id,
                        items,
                        notify=should_notify,
                    )
                    # The Avito workflow is complete at this point. Persist its regular
                    # schedule before touching Telegram so a delivery outage cannot turn
                    # into another Avito fetch five minutes later.
                    await self.database.mark_success(search.id, search.interval_seconds)
                except AvitoError as exc:
                    # Persist the global pause before releasing the single Avito
                    # workflow slot.  A simultaneous manual check therefore cannot
                    # enter between the blocked response and cooldown recording.
                    await self._handle_avito_error(search, exc)
                    return CheckResult(0, 0, 0, str(exc))
                except Exception as exc:
                    logger.exception("Неожиданная ошибка поиска #%s", search.id)
                    await self.database.mark_failure(search.id, str(exc), 300)
                    return CheckResult(0, 0, 0, "Внутренняя ошибка проверки")

            try:
                sent = await self._send_pending(search)
            except TelegramForbiddenError:
                await self.database.set_active(search.id, search.chat_id, False)
                await self.database.clear_pending_delivery_retry(search.id)
                logger.warning(
                    "Бот заблокирован в чате %s; поиск #%s приостановлен",
                    search.chat_id,
                    search.id,
                )
                return CheckResult(
                    found=len(items),
                    new=new_count,
                    sent=0,
                    error="Бот заблокирован пользователем",
                )
            except Exception:
                # Pending notifications remain in SQLite. Most importantly, the
                # successful Avito check keeps its normal schedule and failure_count=0.
                logger.exception(
                    "Выдача поиска #%s сохранена, но уведомления пока не отправлены",
                    search.id,
                )
                await self.database.postpone_pending_delivery(
                    search.id, PENDING_DELIVERY_RETRY_SECONDS
                )
                return CheckResult(
                    found=len(items),
                    new=new_count,
                    sent=0,
                    error="Объявления сохранены; отправка уведомлений будет повторена",
                )

            await self.database.clear_pending_delivery_retry(search.id)

            logger.info(
                "Поиск #%s: найдено=%s новых=%s отправлено=%s",
                search.id,
                len(items),
                new_count,
                sent,
            )
            return CheckResult(found=len(items), new=new_count, sent=sent)

    async def _retry_pending_deliveries(self) -> None:
        searches = await self.database.searches_with_pending_items()
        for search in searches:
            lock = self._locks.setdefault(search.id, asyncio.Lock())
            if lock.locked():
                continue
            async with lock:
                try:
                    await self._send_pending(search)
                except TelegramForbiddenError:
                    await self.database.set_active(search.id, search.chat_id, False)
                    await self.database.clear_pending_delivery_retry(search.id)
                except Exception:
                    logger.exception(
                        "Pending Telegram delivery failed for search #%s",
                        search.id,
                    )
                    await self.database.postpone_pending_delivery(
                        search.id, PENDING_DELIVERY_RETRY_SECONDS
                    )
                else:
                    await self.database.clear_pending_delivery_retry(search.id)

    async def _notify_avito_waiting(self, search: Search, exc: AvitoBlockedError) -> None:
        # Block recovery still runs inside AvitoClient, but end users should only
        # receive actual listings. Technical state remains available to operators.
        logger.info("Поиск #%s: Avito временно ограничил доступ: %s", search.id, exc)

    async def _send_pending(self, search: Search) -> int:
        pending = await self.database.pending_items(
            search.id, self.settings.max_notifications_per_check
        )
        sent = 0
        for item in pending:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть на Avito", url=item.url)]]
            )
            try:
                await self._send_item_notification(search, item, keyboard)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                await self._send_item_notification(search, item, keyboard)
            await self.database.mark_notified(search.id, item.id)
            sent += 1
            await asyncio.sleep(0.15)
        return sent

    async def _send_item_notification(
        self,
        search: Search,
        item: AvitoItem,
        keyboard: InlineKeyboardMarkup,
    ) -> None:
        text = item_message(search, item)
        if item.image_url:
            try:
                await self.bot.send_photo(
                    chat_id=search.chat_id,
                    photo=item.image_url,
                    caption=text,
                    reply_markup=keyboard,
                )
                return
            except TelegramBadRequest as exc:
                logger.warning(
                    "Telegram не смог загрузить фото объявления %s; отправляю текст: %s",
                    item.id,
                    exc,
                )
        await self.bot.send_message(
            chat_id=search.chat_id,
            text=text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def _handle_avito_error(self, search: Search, exc: AvitoError) -> None:
        blocked = isinstance(exc, AvitoBlockedError)
        retry_seconds = exc.retry_after_seconds
        if retry_seconds is None:
            if isinstance(exc, AvitoParseError):
                # A schema/layout change is not repaired by hammering the same page.
                retry_seconds = min(21_600, 3600 * (2 ** min(search.failure_count, 3)))
            else:
                retry_seconds = (
                    1800 if blocked else min(1800, 60 * (2 ** min(search.failure_count, 4)))
                )
        if exc.retry_after_seconds is not None:
            await self.database.postpone_active_searches(retry_seconds)
        await self.database.mark_failure(search.id, str(exc), retry_seconds)
        logger.warning("Поиск #%s не проверен: %s", search.id, exc)
