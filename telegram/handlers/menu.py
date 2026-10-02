from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram.keyboards import ButtonBuilder
from telegram.utils import show


router = Router()

MAIN_MENU_TEXT = "<b>Выберите действие:</b>"


@router.message(CommandStart())
@router.message(Command("menu"))
async def start_command(
        message: Message,
        state: FSMContext,
        is_admin: bool,
    ) -> None:
    """Выводит основное меню."""
    await state.clear()
    await message.answer(
        MAIN_MENU_TEXT, reply_markup=ButtonBuilder.main_menu(is_admin)
    )


@router.message(Command("cancel"))
async def cancel_command(
        message: Message,
        state: FSMContext,
        is_admin: bool,
    ) -> None:
    """Прерывает текущий ввод и возвращает в меню."""
    await state.clear()
    await message.answer(
        f"Действие отменено.\n\n{MAIN_MENU_TEXT}",
        reply_markup=ButtonBuilder.main_menu(is_admin),
    )


@router.message(Command("id"))
async def id_command(message: Message) -> None:
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>"
    )


@router.callback_query(F.data.in_({"main_menu", "cancel"}))
async def main_menu_callback(callback: CallbackQuery, is_admin: bool) -> None:
    # Незаконченный ввод сбрасывает ResetStateMiddleware.
    await show(callback, MAIN_MENU_TEXT, ButtonBuilder.main_menu(is_admin))
