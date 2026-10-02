from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# Причины списания, которые выбираются кнопками. «Другая причина» вводится
# текстом и сюда не входит.
WRITE_OFF_REASONS = {
    "expired": "Просрочено",
    "damaged": "Повреждено",
    "staff": "Для сотрудника",
}

ROLE_TITLES = {
    "admin": "Администратор",
    "employee": "Сотрудник",
}

QUICK_STORAGE_DAYS = (1, 2, 3, 5, 7)

Rows = list[list[InlineKeyboardButton]]


def button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def menu_row() -> list[InlineKeyboardButton]:
    return [button("🏠 В меню", "main_menu")]


class ButtonBuilder:
    """Клавиатуры бота. Данные приходят из обработчиков, здесь только кнопки."""

    @staticmethod
    def main_menu(is_admin: bool) -> InlineKeyboardMarkup:
        rows = [
            [button("📦 Достать из заморозки 📦", "defrost_page_1")],
            [button("❄️ Добавить заморозку ❄️", "delivery_page_1")],
            [button("⚠️ Сегодня заканчивается срок ⚠️", "expiring")],
            [button("🗑️ Списание и продажа 📈", "batch_page_1")],
            [button("📊 Остатки 📊", "stock")],
            [button("📋 История списаний 📋", "history_page_1")],
        ]
        if is_admin:
            rows.append([button("⚙️ Настройки ⚙️", "settings")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def menu(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
        """Переданные ряды кнопок и «🏠 В меню» под ними."""
        return InlineKeyboardMarkup(inline_keyboard=[*rows, menu_row()])

    @staticmethod
    def cancel(back_callback: str | None = None) -> InlineKeyboardMarkup:
        """Кнопка отмены для шагов, где бот ждёт текст."""
        if back_callback is not None:
            return InlineKeyboardMarkup(inline_keyboard=[
                [button("⬅️ Назад", back_callback)],
            ])
        return InlineKeyboardMarkup(inline_keyboard=[
            [button("❌ Отмена", "cancel")],
        ])

    @staticmethod
    def paginated(
        items: list[tuple[str, str]],
        section: str,
        page: int,
        page_count: int,
        extra_rows: Rows | None = None,
    ) -> InlineKeyboardMarkup:
        """Кнопки страницы, под ними «⬅️ Назад», «🔍 Поиск», «Далее ➡️»."""
        rows = [[button(text, data)] for text, data in items]

        navigation = []
        if page > 1:
            navigation.append(button("⬅️ Назад", f"{section}_page_{page - 1}"))
        navigation.append(button("🔍 Поиск", f"{section}_search"))
        if page < page_count:
            navigation.append(button("Далее ➡️", f"{section}_page_{page + 1}"))
        rows.append(navigation)

        rows.extend(extra_rows or [])
        rows.append(menu_row())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def search_results(
        items: list[tuple[str, str]],
        section: str,
    ) -> InlineKeyboardMarkup:
        rows = [[button(text, data)] for text, data in items]
        rows.append([
            button("🔍 Новый поиск", f"{section}_search"),
            button("📋 Весь список", f"{section}_page_1"),
        ])
        rows.append(menu_row())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def pages(section: str, page: int, page_count: int) -> InlineKeyboardMarkup:
        """Листание страниц без поиска."""
        navigation = []
        if page > 1:
            navigation.append(button("⬅️ Назад", f"{section}_page_{page - 1}"))
        if page < page_count:
            navigation.append(button("Далее ➡️", f"{section}_page_{page + 1}"))
        rows = [navigation] if navigation else []
        rows.append(menu_row())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def quantity(
        section: str,
        item_id: int,
        max_quantity: int | None = None,
    ) -> InlineKeyboardMarkup:
        """1, 2, 3 и «📝 Ввести число». Кнопки больше остатка не выводятся."""
        counts = [
            count for count in (1, 2, 3)
            if max_quantity is None or count <= max_quantity
        ]
        rows = [[
            button(str(count), f"{section}_count_{item_id}_{count}")
            for count in counts
        ]]
        rows.append([button("📝 Ввести число", f"{section}_input_{item_id}")])
        rows.append([
            button("⬅️ К списку", f"{section}_page_1"),
            button("🏠 В меню", "main_menu"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def back_to_list(section: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                button("⬅️ К списку", f"{section}_page_1"),
                button("🏠 В меню", "main_menu"),
            ],
        ])

    @staticmethod
    def confirm(yes_callback: str, no_callback: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                button("✅ Да", yes_callback),
                button("❌ Нет", no_callback),
            ],
        ])

    @staticmethod
    def expiring(batch_count: int) -> InlineKeyboardMarkup:
        return ButtonBuilder.menu(
            [button(f"🗑 Списать всё (партий: {batch_count})", "expiring_clear")],
            [button("🔄 Обновить", "expiring")],
        )

    @staticmethod
    def batch_actions(batch_id: int) -> InlineKeyboardMarkup:
        return ButtonBuilder.menu(
            [
                button("🗑 Списать", f"batch_writeoff_{batch_id}"),
                button("💰 Продано", f"batch_sale_{batch_id}"),
            ],
            [button("⬅️ К списку", "batch_page_1")],
        )

    @staticmethod
    def write_off_reasons(batch_id: int) -> InlineKeyboardMarkup:
        rows = [
            [button(title, f"batch_reason_{batch_id}_{code}")]
            for code, title in WRITE_OFF_REASONS.items()
        ]
        rows.append([
            button("✏️ Другая причина", f"batch_reason_{batch_id}_other")
        ])
        rows.append([button("⬅️ Назад", f"batch_select_{batch_id}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def whole_batch(batch_id: int, quantity: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [button(f"Вся партия — {quantity} шт.", f"batch_all_{batch_id}")],
            [button("❌ Отмена", "cancel")],
        ])

    @staticmethod
    def settings() -> InlineKeyboardMarkup:
        return ButtonBuilder.menu(
            [button("📦 Товары", "prod_page_1")],
            [button("👥 Сотрудники", "user_list")],
        )

    @staticmethod
    def storage_days(callback_prefix: str, back_callback: str | None = None) -> InlineKeyboardMarkup:
        """Быстрый выбор срока хранения: callback_prefix + количество дней."""
        rows = [[
            button(f"{days} дн.", f"{callback_prefix}{days}")
            for days in QUICK_STORAGE_DAYS
        ]]
        if back_callback is not None:
            rows.append([button("⬅️ Назад", back_callback)])
        else:
            rows.append([button("❌ Отмена", "cancel")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def product_card(product_id: int) -> InlineKeyboardMarkup:
        return ButtonBuilder.menu(
            [
                button("✏️ Срок хранения", f"prod_days_{product_id}"),
                button("✏️ Название", f"prod_rename_{product_id}"),
            ],
            [button("🗑 Удалить", f"prod_del_{product_id}")],
            [button("⬅️ К товарам", "prod_page_1")],
        )

    @staticmethod
    def users(users: list[dict]) -> InlineKeyboardMarkup:
        rows = []
        for user in users:
            icon = "👑" if user["role"] == "admin" else "👤"
            blocked = "" if user["is_active"] else " ⛔"
            rows.append([button(
                f"{icon} {user['full_name']}{blocked}",
                f"user_view_{user['telegram_id']}",
            )])
        rows.append([button("➕ Добавить сотрудника", "user_add")])
        rows.append([button("⬅️ Настройки", "settings")])
        rows.append(menu_row())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def user_card(user: dict, is_self: bool) -> InlineKeyboardMarkup:
        rows = []
        telegram_id = user["telegram_id"]
        if not is_self:
            if user["role"] == "admin":
                rows.append([button(
                    "👤 Сделать сотрудником", f"user_employee_{telegram_id}"
                )])
            else:
                rows.append([button(
                    "👑 Сделать администратором", f"user_admin_{telegram_id}"
                )])
            if user["is_active"]:
                rows.append([button(
                    "⛔ Отключить доступ", f"user_disable_{telegram_id}"
                )])
            else:
                rows.append([button(
                    "✅ Вернуть доступ", f"user_enable_{telegram_id}"
                )])
        rows.append([button("⬅️ К сотрудникам", "user_list")])
        rows.append(menu_row())
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def new_user_role() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [button("👤 Сотрудник", "user_newrole_employee")],
            [button("👑 Администратор", "user_newrole_admin")],
            [button("❌ Отмена", "cancel")],
        ])
