from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.callback_answer import CallbackAnswer

from storage.db import Database
from telegram.keyboards import ROLE_TITLES, ButtonBuilder, button
from telegram.middlewares import IsAdmin
from telegram.states import UserStates
from telegram.utils import MAX_NAME_LENGTH, clean_name, esc, parse_ids, show


# «⚙️ Настройки» → «👥 Сотрудники». Только администратор.
# Сотрудники не регистрируются сами: администратор вводит Telegram ID и имя.
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

USER_GONE_TEXT = "Такого пользователя нет."
MAX_TELEGRAM_ID = 2 ** 53  # Telegram ID укладываются в 52 бита


def _users_text(users: list[dict]) -> str:
    text = (
        "👥 <b>Сотрудники</b>\n\n"
        "👑 — администратор, 👤 — сотрудник, ⛔ — доступ отключён"
    )
    if not users:
        text += "\n\nПока никто не добавлен."
    return text


def _user_card(user: dict, is_self: bool) -> str:
    access = "✅ есть" if user["is_active"] else "⛔ отключён"
    text = (
        f"{'👑' if user['role'] == 'admin' else '👤'} "
        f"<b>{esc(user['full_name'])}</b>\n\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n"
        f"Роль: {ROLE_TITLES[user['role']]}\n"
        f"Доступ: {access}"
    )
    if is_self:
        text += "\n\nЭто вы — свою роль и доступ изменить нельзя."
    return text


async def _show_user_card(
        callback: CallbackQuery,
        db: Database,
        telegram_id: int,
    ) -> None:
    user = db.get_user(telegram_id)
    if user is None:
        await show(
            callback,
            USER_GONE_TEXT,
            ButtonBuilder.menu([button("⬅️ К сотрудникам", "user_list")]),
        )
        return

    is_self = telegram_id == callback.from_user.id
    await show(
        callback,
        _user_card(user, is_self),
        ButtonBuilder.user_card(user, is_self),
    )


async def _update_user(
        callback: CallbackQuery,
        callback_answer: CallbackAnswer,
        db: Database,
        prefix: str,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> None:
    """Меняет роль или доступ и снова показывает карточку пользователя."""
    ids = parse_ids(callback.data, prefix)
    if not ids:
        await show(callback, USER_GONE_TEXT, ButtonBuilder.menu())
        return

    telegram_id = ids[0]
    if telegram_id == callback.from_user.id:
        callback_answer.text = "Нельзя менять свою роль и доступ"
        callback_answer.show_alert = True
        return

    try:
        if role is not None:
            db.set_user_role(telegram_id, role)
        if is_active is not None:
            db.set_user_active(telegram_id, is_active)
    except ValueError:
        pass  # Пользователя уже нет — карточка покажет это.

    await _show_user_card(callback, db, telegram_id)


@router.callback_query(F.data == "user_list")
async def users_list_callback(callback: CallbackQuery, db: Database) -> None:
    users = db.users_list()
    await show(callback, _users_text(users), ButtonBuilder.users(users))


@router.callback_query(F.data.startswith("user_view_"))
async def user_view_callback(callback: CallbackQuery, db: Database) -> None:
    ids = parse_ids(callback.data, "user_view_")
    await _show_user_card(callback, db, ids[0] if ids else 0)


@router.callback_query(F.data.startswith("user_admin_"))
async def user_admin_callback(
        callback: CallbackQuery,
        callback_answer: CallbackAnswer,
        db: Database,
    ) -> None:
    await _update_user(callback, callback_answer, db, "user_admin_", role="admin")


@router.callback_query(F.data.startswith("user_employee_"))
async def user_employee_callback(
        callback: CallbackQuery,
        callback_answer: CallbackAnswer,
        db: Database,
    ) -> None:
    await _update_user(callback, callback_answer, db, "user_employee_", role="employee")


@router.callback_query(F.data.startswith("user_disable_"))
async def user_disable_callback(
        callback: CallbackQuery,
        callback_answer: CallbackAnswer,
        db: Database,
    ) -> None:
    await _update_user(callback, callback_answer, db, "user_disable_", is_active=False)


@router.callback_query(F.data.startswith("user_enable_"))
async def user_enable_callback(
        callback: CallbackQuery,
        callback_answer: CallbackAnswer,
        db: Database,
    ) -> None:
    await _update_user(callback, callback_answer, db, "user_enable_", is_active=True)


@router.callback_query(F.data == "user_add")
async def user_add_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserStates.telegram_id)
    await show(
        callback,
        "➕ <b>Новый сотрудник</b>\n\n"
        "Введите Telegram ID сотрудника (число).\n\n"
        "Сотрудник может узнать свой ID, написав боту любое сообщение: "
        "бот ответит, что доступа нет, и покажет ID.",
        ButtonBuilder.cancel(),
    )


@router.message(UserStates.telegram_id, F.text)
async def user_telegram_id_message(
        message: Message,
        state: FSMContext,
        db: Database,
    ) -> None:
    text = message.text.strip()
    if not text.isdigit() or not 0 < int(text) < MAX_TELEGRAM_ID:
        await message.answer(
            "Telegram ID — это число, например 123456789. Введите его ещё раз:",
            reply_markup=ButtonBuilder.cancel(),
        )
        return

    telegram_id = int(text)
    existing = db.get_user(telegram_id)
    if existing is not None:
        await message.answer(
            f"Пользователь с ID <code>{telegram_id}</code> уже есть: "
            f"{esc(existing['full_name'])}.\n\nВведите другой ID:",
            reply_markup=ButtonBuilder.menu(
                [button("👤 Открыть карточку", f"user_view_{telegram_id}")],
                [button("❌ Отмена", "cancel")],
            ),
        )
        return

    await state.set_state(UserStates.full_name)
    await state.update_data(telegram_id=telegram_id)
    await message.answer(
        "Введите имя сотрудника, как оно будет отображаться в боте:",
        reply_markup=ButtonBuilder.cancel(),
    )


@router.message(UserStates.full_name, F.text)
async def user_full_name_message(message: Message, state: FSMContext) -> None:
    full_name = clean_name(message.text)
    if not full_name or len(full_name) > MAX_NAME_LENGTH:
        await message.answer(
            f"Имя должно быть от 1 до {MAX_NAME_LENGTH} символов. "
            "Введите ещё раз:",
            reply_markup=ButtonBuilder.cancel(),
        )
        return

    await state.set_state(UserStates.role)
    await state.update_data(full_name=full_name)
    await message.answer(
        f"Какую роль назначить <b>{esc(full_name)}</b>?",
        reply_markup=ButtonBuilder.new_user_role(),
    )


@router.callback_query(
    UserStates.role,
    F.data.startswith("user_newrole_"),
    flags={"keep_state": True},
)
async def user_role_callback(
        callback: CallbackQuery,
        state: FSMContext,
        db: Database,
        bot: Bot,
    ) -> None:
    role = callback.data.removeprefix("user_newrole_")
    data = await state.get_data()
    await state.clear()
    if role not in ROLE_TITLES:
        await show(callback, "Неизвестная роль.", ButtonBuilder.menu())
        return

    keyboard = ButtonBuilder.menu([button("⬅️ К сотрудникам", "user_list")])
    try:
        db.add_user(data["telegram_id"], data["full_name"], role)
    except ValueError as error:
        await show(callback, f"⚠️ {esc(error)}", keyboard)
        return

    try:
        await bot.send_message(
            data["telegram_id"],
            "✅ Вам открыт доступ к боту учёта продукции. Нажмите /start",
        )
        delivery_note = "Сотруднику отправлено уведомление."
    except TelegramAPIError:
        delivery_note = (
            "Уведомление не доставлено: сотрудник ещё не запускал бота. "
            "Попросите его нажать /start."
        )

    await show(
        callback,
        f"✅ <b>{esc(data['full_name'])}</b> добавлен(а) "
        f"как «{ROLE_TITLES[role]}».\n\n{delivery_note}",
        keyboard,
    )
