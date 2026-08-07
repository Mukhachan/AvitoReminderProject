from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from .avito import build_search_url
from .database import Database
from .models import Search
from .service import CheckResult, MonitorService, format_price

router = Router(name=__name__)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить поиск"), KeyboardButton(text="📋 Мои поиски")],
        [KeyboardButton(text="ℹ️ Помощь")],
    ],
    resize_keyboard=True,
)

SKIP_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True, one_time_keyboard=True
)


class AddSearch(StatesGroup):
    query = State()
    city = State()
    price_min = State()
    price_max = State()


BOT_COMMANDS = [
    BotCommand(command="start", description="Открыть главное меню"),
    BotCommand(command="add", description="Добавить поиск Avito"),
    BotCommand(command="list", description="Показать мои поиски"),
    BotCommand(command="check", description="Проверить поиск сейчас"),
    BotCommand(command="pause", description="Приостановить поиск"),
    BotCommand(command="resume", description="Возобновить поиск"),
    BotCommand(command="delete", description="Удалить поиск"),
    BotCommand(command="cancel", description="Отменить ввод"),
    BotCommand(command="help", description="Помощь"),
]


def _command_argument(message: Message) -> str:
    text = message.text or ""
    return text.partition(" ")[2].strip()


def _parse_price(value: str) -> int | None:
    normalized = value.strip().lower()
    if normalized in {"", "-", "нет", "пропустить", "0"}:
        return None
    digits = re.sub(r"[\s₽руб.]", "", normalized)
    if not digits.isdigit():
        raise ValueError("Введите целое число или «Пропустить»")
    price = int(digits)
    if price > 2_000_000_000:
        raise ValueError("Слишком большое значение цены")
    return price


def _search_keyboard(search: Search) -> InlineKeyboardMarkup:
    toggle_action = "pause" if search.active else "resume"
    toggle_text = "⏸ Приостановить" if search.active else "▶️ Возобновить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Проверить", callback_data=f"search:check:{search.id}")],
            [
                InlineKeyboardButton(
                    text=toggle_text, callback_data=f"search:{toggle_action}:{search.id}"
                )
            ],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"search:delete:{search.id}")],
        ]
    )


def _search_text(search: Search) -> str:
    status = "активен" if search.active else "приостановлен"
    price = f"{format_price(search.price_min)} — {format_price(search.price_max)}"
    if search.price_min is None and search.price_max is None:
        price = "любая цена"
    error = f"\nПоследняя ошибка: {html.escape(search.last_error)}" if search.last_error else ""
    return (
        f"<b>Поиск #{search.id}</b> · {status}\n"
        f"🔎 {html.escape(search.query)}\n"
        f"📍 {html.escape(search.city)}\n"
        f"💰 {price}{error}"
    )


def _result_text(result: CheckResult) -> str:
    if result.error:
        return f"⚠️ Проверка не выполнена: {html.escape(result.error)}"
    return (
        f"Проверка завершена: найдено {result.found}, новых {result.new}, отправлено {result.sent}."
    )


async def _create_search(
    message: Message,
    database: Database,
    service: MonitorService,
    *,
    query: str,
    city: str,
    price_min: int | None,
    price_max: int | None,
) -> None:
    existing = await database.list_searches(message.chat.id)
    if len(existing) >= 20:
        await message.answer("Достигнут лимит: не более 20 поисков на чат.")
        return
    try:
        url = build_search_url(query, city, price_min, price_max)
    except ValueError as exc:
        await message.answer(f"Не удалось создать поиск: {html.escape(str(exc))}")
        return
    user_id = message.from_user.id if message.from_user else message.chat.id
    search = await database.add_search(
        chat_id=message.chat.id,
        user_id=user_id,
        query=query,
        city=city,
        price_min=price_min,
        price_max=price_max,
        url=url,
    )
    await message.answer(
        f"✅ Поиск #{search.id} создан. Выполняю первую проверку…",
        reply_markup=MAIN_KEYBOARD,
    )
    result = await service.check_search(search)
    await message.answer(_result_text(result), reply_markup=_search_keyboard(search))


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "<b>Avito Reminder</b> следит за новыми объявлениями и присылает их сюда.\n\n"
        "Нажмите «Добавить поиск» или используйте команду /add.",
        reply_markup=MAIN_KEYBOARD,
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def help_message(message: Message) -> None:
    await message.answer(
        "<b>Команды</b>\n"
        "/add — пошагово создать поиск\n"
        "/add Москва | iPhone 13 | 30000 | 50000 — создать одной строкой\n"
        "/list — список поисков\n"
        "/check 1 — проверить поиск №1\n"
        "/pause 1, /resume 1, /delete 1 — управление поиском\n"
        "/cancel — отменить текущий ввод",
        reply_markup=MAIN_KEYBOARD,
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ввод отменён.", reply_markup=MAIN_KEYBOARD)


@router.message(Command("add"))
@router.message(F.text == "➕ Добавить поиск")
async def add_search_start(
    message: Message, state: FSMContext, database: Database, service: MonitorService
) -> None:
    argument = _command_argument(message)
    if argument:
        parts = [part.strip() for part in argument.split("|")]
        if len(parts) != 4:
            await message.answer(
                "Формат: /add Город | Запрос | Цена от | Цена до\n"
                "Пример: /add Москва | iPhone 13 | 30000 | 50000"
            )
            return
        try:
            price_min = _parse_price(parts[2])
            price_max = _parse_price(parts[3])
        except ValueError as exc:
            await message.answer(html.escape(str(exc)))
            return
        await _create_search(
            message,
            database,
            service,
            query=parts[1],
            city=parts[0],
            price_min=price_min,
            price_max=price_max,
        )
        return

    await state.set_state(AddSearch.query)
    await message.answer(
        "Что ищем? Например: <b>iPhone 13 128GB</b>", reply_markup=ReplyKeyboardRemove()
    )


@router.message(AddSearch.query, F.text)
async def add_query(message: Message, state: FSMContext) -> None:
    query = " ".join((message.text or "").split())
    if not 2 <= len(query) <= 120:
        await message.answer("Запрос должен содержать от 2 до 120 символов.")
        return
    await state.update_data(query=query)
    await state.set_state(AddSearch.city)
    await message.answer("В каком городе искать? Например: <b>Москва</b>")


@router.message(AddSearch.city, F.text)
async def add_city(message: Message, state: FSMContext) -> None:
    city = " ".join((message.text or "").split())
    if not 2 <= len(city) <= 80:
        await message.answer("Название города должно содержать от 2 до 80 символов.")
        return
    await state.update_data(city=city)
    await state.set_state(AddSearch.price_min)
    await message.answer("Минимальная цена?", reply_markup=SKIP_KEYBOARD)


@router.message(AddSearch.price_min, F.text)
async def add_price_min(message: Message, state: FSMContext) -> None:
    try:
        value = _parse_price(message.text or "")
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    await state.update_data(price_min=value)
    await state.set_state(AddSearch.price_max)
    await message.answer("Максимальная цена?", reply_markup=SKIP_KEYBOARD)


@router.message(AddSearch.price_max, F.text)
async def add_price_max(
    message: Message, state: FSMContext, database: Database, service: MonitorService
) -> None:
    try:
        price_max = _parse_price(message.text or "")
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    data = await state.get_data()
    price_min = data.get("price_min")
    if isinstance(price_min, int) and price_max is not None and price_min > price_max:
        await message.answer("Максимальная цена не может быть меньше минимальной.")
        return
    await state.clear()
    await _create_search(
        message,
        database,
        service,
        query=str(data["query"]),
        city=str(data["city"]),
        price_min=price_min if isinstance(price_min, int) else None,
        price_max=price_max,
    )


@router.message(Command("list"))
@router.message(F.text == "📋 Мои поиски")
async def list_searches(message: Message, database: Database) -> None:
    searches = await database.list_searches(message.chat.id)
    if not searches:
        await message.answer("У вас пока нет поисков. Создайте первый через /add.")
        return
    await message.answer(f"Ваши поиски: {len(searches)}")
    for search in searches:
        await message.answer(_search_text(search), reply_markup=_search_keyboard(search))


async def _id_from_command(message: Message) -> int | None:
    argument = _command_argument(message)
    if not argument.isdigit():
        await message.answer("Укажите номер поиска. Например: /check 1")
        return None
    return int(argument)


@router.message(Command("check"))
async def check_command(message: Message, database: Database, service: MonitorService) -> None:
    search_id = await _id_from_command(message)
    if search_id is None:
        return
    search = await database.get_search(search_id, message.chat.id)
    if search is None:
        await message.answer("Поиск не найден.")
        return
    await message.answer("Проверяю…")
    await message.answer(_result_text(await service.check_search(search)))


async def _toggle_command(message: Message, database: Database, active: bool) -> None:
    search_id = await _id_from_command(message)
    if search_id is None:
        return
    changed = await database.set_active(search_id, message.chat.id, active)
    await message.answer("Готово." if changed else "Поиск не найден.")


@router.message(Command("pause"))
async def pause_command(message: Message, database: Database) -> None:
    await _toggle_command(message, database, False)


@router.message(Command("resume"))
async def resume_command(message: Message, database: Database) -> None:
    await _toggle_command(message, database, True)


@router.message(Command("delete"))
async def delete_command(message: Message, database: Database) -> None:
    search_id = await _id_from_command(message)
    if search_id is None:
        return
    deleted = await database.delete_search(search_id, message.chat.id)
    await message.answer("Поиск удалён." if deleted else "Поиск не найден.")


@router.callback_query(F.data.startswith("search:"))
async def search_callback(
    callback: CallbackQuery, database: Database, service: MonitorService
) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    try:
        _, action, raw_id = callback.data.split(":", 2)
        search_id = int(raw_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    chat_id = callback.message.chat.id
    search = await database.get_search(search_id, chat_id)
    if search is None:
        await callback.answer("Поиск уже удалён", show_alert=True)
        return

    if action == "check":
        await callback.answer("Проверяю…")
        result = await service.check_search(search)
        await callback.message.answer(_result_text(result))
    elif action in {"pause", "resume"}:
        active = action == "resume"
        await database.set_active(search_id, chat_id, active)
        await callback.answer("Поиск возобновлён" if active else "Поиск приостановлен")
        updated = await database.get_search(search_id, chat_id)
        if updated:
            await callback.message.edit_text(
                _search_text(updated), reply_markup=_search_keyboard(updated)
            )
    elif action == "delete":
        await database.delete_search(search_id, chat_id)
        await callback.answer("Поиск удалён")
        await callback.message.edit_text(f"Поиск #{search_id} удалён.")
    else:
        await callback.answer("Неизвестная команда", show_alert=True)
