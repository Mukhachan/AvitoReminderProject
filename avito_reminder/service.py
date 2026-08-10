from __future__ import annotations

import asyncio
import html
import logging
from contextlib import suppress
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)

from .avito import AvitoBlockedError, AvitoClient, AvitoError
from .config import Settings
from .database import Database
from .models import AvitoItem, Search

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CheckResult:
    found: int
    new: int
    sent: int
    error: str | None = None


def format_price(price: int | None) -> str:
    return "Цена не указана" if price is None else f"{price:,} ₽".replace(",", " ")


def item_message(search: Search, item: AvitoItem) -> str:
    parts = [
        f"🔔 <b>Новое объявление по поиску #{search.id}</b>",
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
        self._semaphore = asyncio.Semaphore(3)
        self._cooldown_notified_until: dict[int, float] = {}

    async def run(self) -> None:
        logger.info("Мониторинг Avito запущен")
        while not self._stop.is_set():
            try:
                searches = await self.database.due_searches()
                if searches:
                    await asyncio.gather(
                        *(self.check_search(search) for search in searches),
                        return_exceptions=True,
                    )
            except Exception:
                logger.exception("Ошибка цикла мониторинга")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.scheduler_poll_seconds
                )
        logger.info("Мониторинг Avito остановлен")

    def stop(self) -> None:
        self._stop.set()

    async def check_search(self, search: Search) -> CheckResult:
        lock = self._locks.setdefault(search.id, asyncio.Lock())
        if lock.locked():
            return CheckResult(found=0, new=0, sent=0, error="Проверка уже выполняется")
        async with lock, self._semaphore:
            try:
                async def notify_blocked(exc: AvitoBlockedError) -> None:
                    await self._notify_avito_waiting(search, exc)

                items = await self.client.search(search.url, on_blocked=notify_blocked)
                should_notify = search.initialized or self.settings.notify_initial_results
                new_count = await self.database.record_items(search.id, items, notify=should_notify)
                sent = await self._send_pending(search)
                await self.database.mark_success(search.id, search.interval_seconds)
                logger.info(
                    "Поиск #%s: найдено=%s новых=%s отправлено=%s",
                    search.id,
                    len(items),
                    new_count,
                    sent,
                )
                return CheckResult(found=len(items), new=new_count, sent=sent)
            except TelegramForbiddenError:
                await self.database.set_active(search.id, search.chat_id, False)
                logger.warning(
                    "Бот заблокирован в чате %s; поиск #%s приостановлен", search.chat_id, search.id
                )
                return CheckResult(0, 0, 0, "Бот заблокирован пользователем")
            except AvitoError as exc:
                await self._handle_avito_error(search, exc)
                return CheckResult(0, 0, 0, str(exc))
            except Exception as exc:
                logger.exception("Неожиданная ошибка поиска #%s", search.id)
                await self.database.mark_failure(search.id, str(exc), 300)
                return CheckResult(0, 0, 0, "Внутренняя ошибка проверки")

    async def _notify_avito_waiting(self, search: Search, _exc: AvitoBlockedError) -> None:
        rotation_enabled = (
            self.settings.avito_proxy_mode != "direct"
            and self.settings.avito_proxy_rotation_enabled
            and bool(
                self.settings.avito_proxy_pool
                or self.settings.avito_proxy_change_url
            )
        )
        next_action = (
            "Если блокировка останется, парсер автоматически сменит IP."
            if rotation_enabled
            else "Chromium останется открытым для повторной загрузки."
        )
        wait_min = self.settings.avito_page_reload_delay_seconds
        wait_max = wait_min + self.settings.avito_page_reload_jitter_seconds
        wait_text = str(wait_min) if wait_min == wait_max else f"{wait_min}–{wait_max}"
        text = (
            f"⏳ <b>Поиск #{search.id}: Avito ограничил доступ.</b>\n"
            f"Обновление через {wait_text} секунд. {next_action}"
        )
        try:
            try:
                await self.bot.send_message(search.chat_id, text)
            except TelegramRetryAfter as retry:
                await asyncio.sleep(retry.retry_after)
                await self.bot.send_message(search.chat_id, text)

        except TelegramForbiddenError:
            await self.database.set_active(search.id, search.chat_id, False)

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
                await self.bot.send_message(
                    chat_id=search.chat_id,
                    text=item_message(search, item),
                    reply_markup=keyboard,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                await self.bot.send_message(
                    chat_id=search.chat_id,
                    text=item_message(search, item),
                    reply_markup=keyboard,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            await self.database.mark_notified(search.id, item.id)
            sent += 1
            await asyncio.sleep(0.15)
        return sent

    async def _handle_avito_error(self, search: Search, exc: AvitoError) -> None:
        blocked = isinstance(exc, AvitoBlockedError)
        retry_seconds = exc.retry_after_seconds
        if retry_seconds is None:
            retry_seconds = (
                1800 if blocked else min(1800, 60 * (2 ** min(search.failure_count, 4)))
            )
        if exc.retry_after_seconds is not None:
            await self.database.postpone_active_searches(retry_seconds)
        await self.database.mark_failure(search.id, str(exc), retry_seconds)
        logger.warning("Поиск #%s не проверен: %s", search.id, exc)

        should_notify = search.failure_count in {0, 2, 5}
        if exc.retry_after_seconds is not None:
            loop = asyncio.get_running_loop()
            now = loop.time()
            should_notify = self._cooldown_notified_until.get(search.chat_id, 0) <= now
            if should_notify:
                self._cooldown_notified_until[search.chat_id] = now + retry_seconds

        if should_notify:
            if exc.retry_after_seconds is not None:
                hours = max(1, round(retry_seconds / 3600))
                hint = f" Все запросы к Avito поставлены на паузу примерно на {hours} ч."
            elif blocked:
                hint = (
                    " Avito запросил капчу или ограничил IP. "
                    "Проверьте обычное подключение Raspberry Pi."
                )
            else:
                hint = " Следующая попытка будет выполнена автоматически."
            try:
                error_text = (
                    f"⚠️ Поиск #{search.id} временно не проверен: {html.escape(str(exc))}.{hint}"
                )
                try:
                    await self.bot.send_message(search.chat_id, error_text)
                except TelegramRetryAfter as retry:
                    await asyncio.sleep(retry.retry_after)
                    await self.bot.send_message(search.chat_id, error_text)

            except TelegramForbiddenError:
                await self.database.set_active(search.id, search.chat_id, False)
