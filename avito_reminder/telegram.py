from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
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
from .config import Settings
from .database import Database
from .models import Search
from .service import CheckResult, MonitorService, format_price

router = Router(name=__name__)

CANCEL_TEXT = "❌ Отмена"
BACK_TEXT = "⬅️ Назад"
SKIP_TEXT = "Без ограничения"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить поиск"), KeyboardButton(text="📋 Мои поиски")],
        [KeyboardButton(text="📊 Статус"), KeyboardButton(text="ℹ️ Помощь")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие",
)

QUERY_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=CANCEL_TEXT)]],
    resize_keyboard=True,
)

CITY_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Москва"), KeyboardButton(text="Санкт-Петербург")],
        [KeyboardButton(text="Вся Россия")],
        [KeyboardButton(text=BACK_TEXT), KeyboardButton(text=CANCEL_TEXT)],
    ],
    resize_keyboard=True,
)

PRICE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=SKIP_TEXT)],
        [KeyboardButton(text=BACK_TEXT), KeyboardButton(text=CANCEL_TEXT)],
    ],
    resize_keyboard=True,
)

INTERVAL_OPTIONS = {
    "15 минут": 15 * 60,
    "30 минут": 30 * 60,
    "1 час": 60 * 60,
    "3 часа": 3 * 60 * 60,
    "6 часов": 6 * 60 * 60,
    "24 часа": 24 * 60 * 60,
}

INTERVAL_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="15 минут"), KeyboardButton(text="30 минут")],
        [KeyboardButton(text="1 час"), KeyboardButton(text="3 часа")],
        [KeyboardButton(text="6 часов"), KeyboardButton(text="24 часа")],
        [KeyboardButton(text=BACK_TEXT), KeyboardButton(text=CANCEL_TEXT)],
    ],
    resize_keyboard=True,
)


class AddSearch(StatesGroup):
    query = State()
    city = State()
    price_min = State()
    price_max = State()
    interval = State()
    confirm = State()


BOT_COMMANDS = [
    BotCommand(command="start", description="Открыть главное меню"),
    BotCommand(command="menu", description="Показать кнопки меню"),
    BotCommand(command="add", description="Создать поиск по шагам"),
    BotCommand(command="list", description="Показать мои поиски"),
    BotCommand(command="status", description="Сводка мониторинга"),
    BotCommand(command="check", description="Проверить поиск сейчас"),
    BotCommand(command="pause", description="Приостановить поиск"),
    BotCommand(command="resume", description="Возобновить поиск"),
    BotCommand(command="delete", description="Удалить поиск"),
    BotCommand(command="cancel", description="Отменить текущий ввод"),
    BotCommand(command="help", description="Помощь"),
]


def _command_argument(message: Message) -> str:
    text = message.text or ""
    return text.partition(" ")[2].strip()


def _parse_price(value: str) -> int | None:
    normalized = value.strip().lower()
    if normalized in {"", "-", "нет", "пропустить", "без ограничения", "0"}:
        return None
    digits = re.sub(r"[\s₽руб.]", "", normalized)
    if not digits.isdigit():
        raise ValueError("Введите целое число или нажмите «Без ограничения»")
    price = int(digits)
    if price > 2_000_000_000:
        raise ValueError("Слишком большое значение цены")
    return price


def _parse_interval(value: str) -> int:
    normalized = " ".join(value.strip().lower().split())
    for label, seconds in INTERVAL_OPTIONS.items():
        if normalized == label.lower():
            return seconds

    match = re.fullmatch(r"(\d+)\s*(мин(?:ут[а-я]*)?|ч(?:ас(?:а|ов)?)?)", normalized)
    if not match:
        raise ValueError("Выберите интервал кнопкой или введите, например, «45 минут»")
    amount = int(match.group(1))
    seconds = amount * (3600 if match.group(2).startswith(("ч", "час")) else 60)
    if seconds < 15 * 60:
        raise ValueError("Минимальный интервал — 15 минут")
    if seconds > 24 * 60 * 60:
        raise ValueError("Максимальный интервал — 24 часа")
    return seconds


def _format_interval(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        if hours == 1:
            return "1 час"
        if 2 <= hours <= 4:
            return f"{hours} часа"
        return f"{hours} часов"
    return f"{seconds // 60} минут"


def _price_range(price_min: int | None, price_max: int | None) -> str:
    if price_min is None and price_max is None:
        return "любая цена"
    if price_min is None:
        return f"до {format_price(price_max)}"
    if price_max is None:
        return f"от {format_price(price_min)}"
    return f"{format_price(price_min)} — {format_price(price_max)}"


def _search_keyboard(search: Search) -> InlineKeyboardMarkup:
    toggle_action = "pause" if search.active else "resume"
    toggle_text = "⏸ Приостановить" if search.active else "▶️ Возобновить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔗 Открыть Avito", url=search.url),
                InlineKeyboardButton(
                    text="🔄 Проверить",
                    callback_data=f"search:check:{search.id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"search:{toggle_action}:{search.id}",
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"search:delete-ask:{search.id}",
                ),
            ],
        ]
    )


async def _safe_edit_text(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Ignore Telegram's harmless error when a card already has the requested content."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
        return False


def _delete_keyboard(search_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"search:delete:{search_id}",
                ),
                InlineKeyboardButton(
                    text="Не удалять",
                    callback_data=f"search:delete-cancel:{search_id}",
                ),
            ]
        ]
    )


def _confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать поиск", callback_data="add:confirm")],
            [InlineKeyboardButton(text="✏️ Заполнить заново", callback_data="add:restart")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel")],
        ]
    )


def _search_text(search: Search) -> str:
    status = "🟢 активен" if search.active else "⏸ приостановлен"
    return (
        f"<b>Поиск #{search.id}</b> · {status}\n"
        f"🔎 {html.escape(search.query)}\n"
        f"📍 {html.escape(search.city)}\n"
        f"💰 {_price_range(search.price_min, search.price_max)}\n"
        f"⏱ Каждые {_format_interval(search.interval_seconds)}\n"
    )


def _confirmation_text(data: dict[str, object]) -> str:
    price_min = data.get("price_min") if isinstance(data.get("price_min"), int) else None
    price_max = data.get("price_max") if isinstance(data.get("price_max"), int) else None
    interval = data.get("interval_seconds")
    interval_seconds = interval if isinstance(interval, int) else 15 * 60
    return (
        "<b>Проверьте параметры поиска</b>\n\n"
        f"🔎 Товар: <b>{html.escape(str(data['query']))}</b>\n"
        f"📍 Где: <b>{html.escape(str(data['city']))}</b>\n"
        f"💰 Цена: <b>{_price_range(price_min, price_max)}</b>\n"
        f"⏱ Проверять: <b>каждые {_format_interval(interval_seconds)}</b>\n\n"
        "Создать этот поиск?"
    )


def _result_text(result: CheckResult) -> str:
    if result.error:
        return f"⚠️ Проверка не выполнена: {html.escape(result.error)}"
    return (
        f"✅ Проверка завершена: найдено {result.found}, "
        f"новых {result.new}, отправлено {result.sent}."
    )


async def _ask_query(message: Message) -> None:
    await message.answer(
        "<b>Шаг 1 из 5 · Что ищем?</b>\n\n"
        "Напишите название товара так, как искали бы его на Avito.\n"
        "Например: <i>iPhone 13 128 GB</i>",
        reply_markup=QUERY_KEYBOARD,
    )


async def _ask_city(message: Message) -> None:
    await message.answer(
        "<b>Шаг 2 из 5 · Где искать?</b>\n\n"
        "Выберите популярный вариант или напишите свой город.",
        reply_markup=CITY_KEYBOARD,
    )


async def _ask_price_min(message: Message) -> None:
    await message.answer(
        "<b>Шаг 3 из 5 · Минимальная цена</b>\n\n"
        "Введите сумму в рублях или нажмите «Без ограничения».",
        reply_markup=PRICE_KEYBOARD,
    )


async def _ask_price_max(message: Message) -> None:
    await message.answer(
        "<b>Шаг 4 из 5 · Максимальная цена</b>\n\n"
        "Введите сумму в рублях или нажмите «Без ограничения».",
        reply_markup=PRICE_KEYBOARD,
    )


async def _ask_interval(message: Message) -> None:
    await message.answer(
        "<b>Шаг 5 из 5 · Частота проверки</b>\n\n"
        "Как часто проверять новые объявления? Рекомендуется 30 минут или реже.",
        reply_markup=INTERVAL_KEYBOARD,
    )


async def _create_search(
    message: Message,
    database: Database,
    *,
    query: str,
    city: str,
    price_min: int | None,
    price_max: int | None,
    interval_seconds: int,
) -> Search | None:
    existing = await database.list_searches(message.chat.id)
    if len(existing) >= 20:
        await message.answer(
            "Достигнут лимит: не более 20 поисков на чат.",
            reply_markup=MAIN_KEYBOARD,
        )
        return None
    try:
        url = build_search_url(query, city, price_min, price_max)
    except ValueError as exc:
        await message.answer(
            f"Не удалось создать поиск: {html.escape(str(exc))}",
            reply_markup=MAIN_KEYBOARD,
        )
        return None
    duplicate = next((search for search in existing if search.url == url), None)
    if duplicate is not None:
        await message.answer(
            f"Такой поиск уже существует.\n\n{_search_text(duplicate)}",
            reply_markup=_search_keyboard(duplicate),
        )
        await message.answer("Главное меню", reply_markup=MAIN_KEYBOARD)
        return None

    user_id = message.from_user.id if message.from_user else message.chat.id
    search = await database.add_search(
        chat_id=message.chat.id,
        user_id=user_id,
        query=query,
        city=city,
        price_min=price_min,
        price_max=price_max,
        interval_seconds=interval_seconds,
        url=url,
    )
    await message.answer(
        "✅ <b>Поиск создан и поставлен в очередь.</b>\n"
        "Первая проверка выполняется автоматически и может занять несколько минут.",
        reply_markup=MAIN_KEYBOARD,
    )
    await message.answer(_search_text(search), reply_markup=_search_keyboard(search))
    return search


@router.message(CommandStart())
@router.message(Command("menu"))
async def start(message: Message, state: FSMContext, database: Database) -> None:
    await state.clear()
    searches = await database.list_searches(message.chat.id)
    active = sum(search.active for search in searches)
    await message.answer(
        "<b>Avito Reminder</b> следит за новыми объявлениями и присылает их сюда.\n\n"
        f"Сейчас у вас поисков: <b>{len(searches)}</b>, активных: <b>{active}</b>.\n"
        "Нажмите «Добавить поиск», чтобы настроить новый мониторинг по шагам.",
        reply_markup=MAIN_KEYBOARD,
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def help_message(message: Message) -> None:
    await message.answer(
        "<b>Как пользоваться ботом</b>\n\n"
        "1. Нажмите «➕ Добавить поиск».\n"
        "2. Ответьте на пять коротких вопросов.\n"
        "3. Проверьте параметры и подтвердите создание.\n"
        "4. Бот будет присылать только новые объявления.\n\n"
        "В разделе «📋 Мои поиски» можно открыть выдачу Avito, запустить проверку, "
        "приостановить или удалить подписку.\n\n"
        "Команды: /add, /list, /status, /check 1, /pause 1, /resume 1, /delete 1.",
        reply_markup=MAIN_KEYBOARD,
    )


@router.message(Command("cancel"))
@router.message(F.text == CANCEL_TEXT)
async def cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    await state.clear()
    text = "Создание поиска отменено." if current_state else "Нет незавершённого ввода."
    await message.answer(text, reply_markup=MAIN_KEYBOARD)


@router.message(Command("add"))
@router.message(F.text == "➕ Добавить поиск")
async def add_search_start(
    message: Message,
    state: FSMContext,
    database: Database,
    settings: Settings,
) -> None:
    await state.clear()
    argument = _command_argument(message)
    if argument:
        parts = [part.strip() for part in argument.split("|")]
        if len(parts) != 4:
            await message.answer(
                "Формат: /add Город | Запрос | Цена от | Цена до\n"
                "Пример: /add Москва | iPhone 13 | 30000 | 50000",
                reply_markup=MAIN_KEYBOARD,
            )
            return
        try:
            price_min = _parse_price(parts[2])
            price_max = _parse_price(parts[3])
        except ValueError as exc:
            await message.answer(html.escape(str(exc)), reply_markup=MAIN_KEYBOARD)
            return
        await _create_search(
            message,
            database,
            query=parts[1],
            city=parts[0],
            price_min=price_min,
            price_max=price_max,
            interval_seconds=max(15 * 60, settings.search_interval_seconds),
        )
        return

    await state.set_state(AddSearch.query)
    await _ask_query(message)


@router.message(AddSearch.query, F.text)
async def add_query(message: Message, state: FSMContext) -> None:
    query = " ".join((message.text or "").split())
    if query == BACK_TEXT:
        await message.answer("Это первый шаг. Введите товар или отмените создание.")
        return
    if not 2 <= len(query) <= 120:
        await message.answer("Запрос должен содержать от 2 до 120 символов.")
        return
    await state.update_data(query=query)
    await state.set_state(AddSearch.city)
    await _ask_city(message)


@router.message(AddSearch.city, F.text)
async def add_city(message: Message, state: FSMContext) -> None:
    city = " ".join((message.text or "").split())
    if city == BACK_TEXT:
        await state.set_state(AddSearch.query)
        await _ask_query(message)
        return
    if not 2 <= len(city) <= 80:
        await message.answer("Название города должно содержать от 2 до 80 символов.")
        return
    await state.update_data(city=city)
    await state.set_state(AddSearch.price_min)
    await _ask_price_min(message)


@router.message(AddSearch.price_min, F.text)
async def add_price_min(message: Message, state: FSMContext) -> None:
    if message.text == BACK_TEXT:
        await state.set_state(AddSearch.city)
        await _ask_city(message)
        return
    try:
        value = _parse_price(message.text or "")
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    await state.update_data(price_min=value)
    await state.set_state(AddSearch.price_max)
    await _ask_price_max(message)


@router.message(AddSearch.price_max, F.text)
async def add_price_max(message: Message, state: FSMContext) -> None:
    if message.text == BACK_TEXT:
        await state.set_state(AddSearch.price_min)
        await _ask_price_min(message)
        return
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
    await state.update_data(price_max=price_max)
    await state.set_state(AddSearch.interval)
    await _ask_interval(message)


@router.message(AddSearch.interval, F.text)
async def add_interval(message: Message, state: FSMContext) -> None:
    if message.text == BACK_TEXT:
        await state.set_state(AddSearch.price_max)
        await _ask_price_max(message)
        return
    try:
        interval_seconds = _parse_interval(message.text or "")
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    await state.update_data(interval_seconds=interval_seconds)
    await state.set_state(AddSearch.confirm)
    data = await state.get_data()
    await message.answer(
        _confirmation_text(data),
        reply_markup=_confirmation_keyboard(),
    )
    await message.answer("Используйте кнопки под сводкой.", reply_markup=ReplyKeyboardRemove())


@router.message(AddSearch.confirm)
async def add_confirmation_hint(message: Message) -> None:
    await message.answer("Подтвердите создание кнопкой под сообщением со сводкой.")


@router.callback_query(AddSearch.confirm, F.data.startswith("add:"))
async def add_search_callback(
    callback: CallbackQuery,
    state: FSMContext,
    database: Database,
) -> None:
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    action = callback.data.partition(":")[2]
    if action == "cancel":
        await state.clear()
        await callback.answer("Отменено")
        await callback.message.edit_text("Создание поиска отменено.")
        await callback.message.answer("Главное меню", reply_markup=MAIN_KEYBOARD)
        return
    if action == "restart":
        await state.clear()
        await state.set_state(AddSearch.query)
        await callback.answer("Начинаем заново")
        await callback.message.edit_text("Заполните параметры поиска заново.")
        await _ask_query(callback.message)
        return
    if action != "confirm":
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    data = await state.get_data()
    required = {"query", "city", "interval_seconds"}
    if not required.issubset(data):
        await state.clear()
        await callback.answer("Данные устарели", show_alert=True)
        await callback.message.answer(
            "Начните создание поиска ещё раз.",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    await state.clear()
    await callback.answer("Создаю поиск")
    await callback.message.edit_reply_markup(reply_markup=None)
    price_min = data.get("price_min") if isinstance(data.get("price_min"), int) else None
    price_max = data.get("price_max") if isinstance(data.get("price_max"), int) else None
    await _create_search(
        callback.message,
        database,
        query=str(data["query"]),
        city=str(data["city"]),
        price_min=price_min,
        price_max=price_max,
        interval_seconds=int(data["interval_seconds"]),
    )


@router.message(Command("list"))
@router.message(F.text == "📋 Мои поиски")
async def list_searches(message: Message, database: Database) -> None:
    searches = await database.list_searches(message.chat.id)
    if not searches:
        await message.answer(
            "У вас пока нет поисков. Нажмите «➕ Добавить поиск».",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    active = sum(search.active for search in searches)
    await message.answer(
        f"<b>Ваши поиски: {len(searches)}</b> · активных {active}",
        reply_markup=MAIN_KEYBOARD,
    )
    for search in searches:
        await message.answer(_search_text(search), reply_markup=_search_keyboard(search))


@router.message(Command("status"))
@router.message(F.text == "📊 Статус")
async def status_message(message: Message, database: Database) -> None:
    searches = await database.list_searches(message.chat.id)
    active = sum(search.active for search in searches)
    paused = len(searches) - active
    errors = sum(bool(search.last_error) for search in searches)
    await message.answer(
        "<b>Состояние мониторинга</b>\n\n"
        f"🔎 Всего поисков: <b>{len(searches)}</b>\n"
        f"🟢 Активных: <b>{active}</b>\n"
        f"⏸ Приостановлено: <b>{paused}</b>\n"
        f"⚠️ С последней ошибкой: <b>{errors}</b>",
        reply_markup=MAIN_KEYBOARD,
    )


async def _id_from_command(message: Message, example: str) -> int | None:
    argument = _command_argument(message)
    if not argument.isdigit():
        await message.answer(f"Укажите номер поиска. Например: /{example} 1")
        return None
    return int(argument)


@router.message(Command("check"))
async def check_command(message: Message, database: Database, service: MonitorService) -> None:
    search_id = await _id_from_command(message, "check")
    if search_id is None:
        return
    search = await database.get_search(search_id, message.chat.id)
    if search is None:
        await message.answer("Поиск не найден.")
        return
    await message.answer("⏳ Проверяю. Из-за режима работы Avito это займёт несколько минут…")
    await message.answer(_result_text(await service.check_search(search)))


async def _toggle_command(message: Message, database: Database, active: bool) -> None:
    command = "resume" if active else "pause"
    search_id = await _id_from_command(message, command)
    if search_id is None:
        return
    changed = await database.set_active(search_id, message.chat.id, active)
    await message.answer("Готово." if changed else "Поиск не найден.", reply_markup=MAIN_KEYBOARD)


@router.message(Command("pause"))
async def pause_command(message: Message, database: Database) -> None:
    await _toggle_command(message, database, False)


@router.message(Command("resume"))
async def resume_command(message: Message, database: Database) -> None:
    await _toggle_command(message, database, True)


@router.message(Command("delete"))
async def delete_command(message: Message, database: Database) -> None:
    search_id = await _id_from_command(message, "delete")
    if search_id is None:
        return
    search = await database.get_search(search_id, message.chat.id)
    if search is None:
        await message.answer("Поиск не найден.")
        return
    await message.answer(
        f"Удалить поиск #{search.id} «{html.escape(search.query)}»?",
        reply_markup=_delete_keyboard(search.id),
    )


@router.callback_query(F.data.startswith("search:"))
async def search_callback(
    callback: CallbackQuery,
    database: Database,
    service: MonitorService,
) -> None:
    if not callback.data or not isinstance(callback.message, Message):
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
        await callback.answer("Проверка запущена")
        progress = await callback.message.answer(
            "⏳ Проверяю. Из-за режима работы Avito это займёт несколько минут…"
        )
        result = await service.check_search(search)
        await progress.edit_text(_result_text(result))
        updated = await database.get_search(search_id, chat_id)
        if updated:
            await _safe_edit_text(
                callback.message,
                _search_text(updated),
                reply_markup=_search_keyboard(updated),
            )
    elif action in {"pause", "resume"}:
        active = action == "resume"
        await database.set_active(search_id, chat_id, active)
        await callback.answer("Поиск возобновлён" if active else "Поиск приостановлен")
        updated = await database.get_search(search_id, chat_id)
        if updated:
            await _safe_edit_text(
                callback.message,
                _search_text(updated),
                reply_markup=_search_keyboard(updated),
            )
    elif action == "delete-ask":
        await callback.answer()
        await callback.message.edit_reply_markup(reply_markup=_delete_keyboard(search_id))
    elif action == "delete-cancel":
        await callback.answer("Удаление отменено")
        await callback.message.edit_reply_markup(reply_markup=_search_keyboard(search))
    elif action == "delete":
        await database.delete_search(search_id, chat_id)
        await callback.answer("Поиск удалён")
        await callback.message.edit_text(f"🗑 Поиск #{search_id} удалён.")
    else:
        await callback.answer("Неизвестная команда", show_alert=True)


@router.message(F.text)
async def unknown_text(message: Message) -> None:
    await message.answer(
        "Не понял сообщение. Выберите действие на клавиатуре или используйте /help.",
        reply_markup=MAIN_KEYBOARD,
    )
