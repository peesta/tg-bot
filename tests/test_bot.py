"""Сценарии работы с ботом: кнопки, ввод текста, доступ."""
import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.helpers import (
    ADMIN_ID, BotTestCase, alerts, callbacks, last_markup, last_text,
    sent_to, texts,
)


EMPLOYEE_ID = 555


def button_texts(requests) -> list[str]:
    markup = last_markup(requests)
    return [button.text for row in markup.inline_keyboard for button in row]


class AccessTest(BotTestCase):
    async def test_stranger_sees_his_id(self):
        requests = await self.send(99, "/start")
        self.assertIn("нет доступа", last_text(requests))
        self.assertIn("<code>99</code>", last_text(requests))

        requests = await self.click(99, "defrost_page_1")
        self.assertEqual(alerts(requests), ["⛔ У вас нет доступа к боту"])
        self.assertEqual(texts(requests), [])

    async def test_disabled_user(self):
        self.db.add_user(EMPLOYEE_ID, "Иван")
        self.db.set_user_active(EMPLOYEE_ID, False)
        self.assertIn("нет доступа", last_text(await self.send(EMPLOYEE_ID, "/start")))

        self.db.set_user_active(EMPLOYEE_ID, True)
        self.assertIn("Выберите действие", last_text(await self.send(EMPLOYEE_ID, "/start")))

    async def test_employee_has_no_settings(self):
        self.db.add_user(EMPLOYEE_ID, "Иван")
        requests = await self.send(EMPLOYEE_ID, "/start")
        self.assertNotIn("settings", callbacks(requests))

        # Даже старой кнопкой в раздел администратора не попасть.
        for data in ("settings", "prod_page_1", "user_list", "gsheet_export_yes"):
            requests = await self.click(EMPLOYEE_ID, data)
            self.assertEqual(texts(requests), [], data)
            self.assertIn("устарела", alerts(requests)[0])

    async def test_admins(self):
        self.db.add_user(777, "Анна", "admin")
        self.assertIn("settings", callbacks(await self.send(777, "/start")))
        self.assertIn("settings", callbacks(await self.send(ADMIN_ID, "/start")))

    async def test_group_messages_are_ignored(self):
        requests = await self.telegram.feed({"message": {
            "message_id": 1, "date": 0,
            "chat": {"id": -100, "type": "group", "title": "Кафе"},
            "from": self.telegram.user(99), "text": "/start",
        }})
        self.assertEqual(requests, [])

    async def test_id_command(self):
        self.assertIn("<code>1</code>", last_text(await self.send(ADMIN_ID, "/id")))


class MenuAndInputTest(BotTestCase):
    async def test_main_menu(self):
        requests = await self.send(ADMIN_ID, "/start")
        self.assertEqual(callbacks(requests), [
            "defrost_page_1", "delivery_page_1", "expiring", "batch_page_1",
            "stock", "history_page_1", "settings",
        ])
        self.assertIn("Выберите действие", last_text(await self.send(ADMIN_ID, "/menu")))

    async def test_cancel_and_plain_text(self):
        await self.click(ADMIN_ID, "delivery_search")
        self.assertIn("Действие отменено", last_text(await self.send(ADMIN_ID, "/cancel")))
        self.assertIn("кнопками меню", last_text(await self.send(ADMIN_ID, "привет")))

    async def test_leaving_input_resets_it(self):
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Медовик", 5)

        await self.click(ADMIN_ID, "defrost_input_1")
        await self.click(ADMIN_ID, "main_menu")
        requests = await self.send(ADMIN_ID, "2")

        self.assertIn("кнопками меню", last_text(requests))
        self.assertEqual(self.db.get_freezer_product("Медовик")["quantity"], 5)

    async def test_sticker_while_waiting_for_text(self):
        await self.click(ADMIN_ID, "defrost_search")
        requests = await self.telegram.feed({"message": {
            "message_id": 1, "date": 0,
            "chat": {"id": ADMIN_ID, "type": "private"},
            "from": self.telegram.user(ADMIN_ID),
            "sticker": {
                "file_id": "x", "file_unique_id": "y", "type": "regular",
                "width": 1, "height": 1, "is_animated": False, "is_video": False,
            },
        }})
        self.assertIn("Пришлите ответ текстом", last_text(requests))

    async def test_unknown_button(self):
        requests = await self.click(ADMIN_ID, "something_old")
        self.assertIn("устарела", alerts(requests)[0])


class ProductsTest(BotTestCase):
    async def test_add_product(self):
        await self.click(ADMIN_ID, "prod_add")
        requests = await self.send(ADMIN_ID, "  Филадельфия   <b>ролл</b> ")
        self.assertIn("Филадельфия &lt;b&gt;ролл&lt;/b&gt;", last_text(requests))
        self.assertIn("prod_newdays_2", callbacks(requests))

        self.assertIn("от 1 до 365", last_text(await self.send(ADMIN_ID, "0")))
        self.assertIn("добавлен", last_text(await self.send(ADMIN_ID, "2")))
        self.assertEqual(
            self.db.get_product("Филадельфия <b>ролл</b>")["fridge_storage_time"], 2
        )

    async def test_add_product_with_button(self):
        await self.click(ADMIN_ID, "prod_add")
        await self.send(ADMIN_ID, "Медовик")
        await self.click(ADMIN_ID, "prod_newdays_3")
        self.assertEqual(self.db.get_product("Медовик")["fridge_storage_time"], 3)

    async def test_duplicate_name_ignores_case(self):
        self.db.new_product("Медовик", 3)
        await self.click(ADMIN_ID, "prod_add")
        self.assertIn("уже есть", last_text(await self.send(ADMIN_ID, "МЕДОВИК")))
        self.assertEqual(self.db.products_list()[0], 1)

    async def test_list_and_search(self):
        for name in ("Калифорния", "Лосось", "Медовик", "Мотти", "Сэндвич", "Чизкейк"):
            self.db.new_product(name, 1)

        requests = await self.click(ADMIN_ID, "prod_page_1")
        self.assertIn("стр. 1/2", last_text(requests))
        self.assertIn("prod_page_2", callbacks(requests))
        self.assertIn("prod_add", callbacks(requests))

        await self.click(ADMIN_ID, "prod_search")
        requests = await self.send(ADMIN_ID, "лос")
        self.assertEqual(
            [data for data in callbacks(requests) if data.startswith("prod_view_")],
            ["prod_view_2"],
        )

    async def test_change_storage_time(self):
        self.db.new_product("Медовик", 3)
        await self.click(ADMIN_ID, "prod_days_1")
        self.assertIn("от 1 до 365", last_text(await self.send(ADMIN_ID, "500")))
        await self.send(ADMIN_ID, "4")
        self.assertEqual(self.db.get_product("Медовик")["fridge_storage_time"], 4)

        await self.click(ADMIN_ID, "prod_setdays_1_5")
        self.assertEqual(self.db.get_product("Медовик")["fridge_storage_time"], 5)

    async def test_rename(self):
        self.db.new_product("Медовик", 3)
        self.db.new_product("Калифорния", 1)
        await self.click(ADMIN_ID, "prod_rename_1")
        self.assertIn("уже есть", last_text(await self.send(ADMIN_ID, "калифорния")))

        # Поменять регистр букв в своём же названии можно.
        self.assertIn("переименован", last_text(await self.send(ADMIN_ID, "медовик")))
        self.assertIsNotNone(self.db.get_product("медовик"))

    async def test_delete(self):
        self.db.new_product("Медовик", 3)
        self.db.new_product("Калифорния", 1)
        self.db.new_delivery("Калифорния", 1)

        self.assertIn("prod_delyes_1", callbacks(await self.click(ADMIN_ID, "prod_del_1")))
        await self.click(ADMIN_ID, "prod_delyes_1")
        self.assertIsNone(self.db.get_product("Медовик"))

        requests = await self.click(ADMIN_ID, "prod_delyes_2")
        self.assertIn("ещё есть в морозильнике", last_text(requests))
        self.assertIsNotNone(self.db.get_product("Калифорния"))


class DeliveryTest(BotTestCase):
    async def test_empty_products(self):
        requests = await self.click(ADMIN_ID, "delivery_page_1")
        self.assertIn("Справочник товаров пуст", last_text(requests))

    async def test_add_to_freezer(self):
        self.db.new_product("Филадельфия", 2)
        self.assertIn("delivery_product_1", callbacks(await self.click(ADMIN_ID, "delivery_page_1")))

        requests = await self.click(ADMIN_ID, "delivery_product_1")
        self.assertEqual(callbacks(requests)[:4], [
            "delivery_count_1_1", "delivery_count_1_2", "delivery_count_1_3",
            "delivery_input_1",
        ])

        requests = await self.click(ADMIN_ID, "delivery_count_1_3")
        self.assertIn("Теперь в морозильнике: 3", last_text(requests))

        await self.click(ADMIN_ID, "delivery_input_1")
        self.assertIn("больше нуля", last_text(await self.send(ADMIN_ID, "0")))
        self.assertIn("Слишком большое", last_text(await self.send(ADMIN_ID, "1000000")))
        await self.send(ADMIN_ID, "7")
        self.assertEqual(self.db.get_freezer_product("Филадельфия")["quantity"], 10)

    async def test_search(self):
        self.db.new_product("Филадельфия", 2)
        self.db.new_product("Медовик", 3)
        await self.click(ADMIN_ID, "delivery_search")
        requests = await self.send(ADMIN_ID, "мед")
        self.assertIn("delivery_product_2", callbacks(requests))
        self.assertNotIn("delivery_product_1", callbacks(requests))


class DefrostTest(BotTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Филадельфия", 2)
        self.db.new_product("Медовик", 3)
        self.db.new_delivery("Филадельфия", 10)  # в морозильнике id 1
        self.db.new_delivery("Медовик", 2)       # в морозильнике id 2

    async def test_list(self):
        requests = await self.click(ADMIN_ID, "defrost_page_1")
        self.assertEqual(callbacks(requests)[:2], ["defrost_product_2", "defrost_product_1"])
        self.assertIn("defrost_search", callbacks(requests))

    async def test_count_buttons_not_more_than_stock(self):
        requests = await self.click(ADMIN_ID, "defrost_product_2")
        self.assertIn("defrost_count_2_2", callbacks(requests))
        self.assertNotIn("defrost_count_2_3", callbacks(requests))

    async def test_defrost_with_button(self):
        requests = await self.click(ADMIN_ID, "defrost_count_1_3")
        expected = (datetime.now() + timedelta(days=2)).strftime("%d.%m.%Y")
        self.assertIn("Годен до", last_text(requests))
        self.assertIn(expected, last_text(requests))
        self.assertEqual(self.db.get_freezer_product("Филадельфия")["quantity"], 7)
        self.assertEqual(self.db.fridge_batches_list()[0]["quantity"], 3)

    async def test_defrost_with_input(self):
        await self.click(ADMIN_ID, "defrost_input_1")
        self.assertIn("только 10", last_text(await self.send(ADMIN_ID, "50")))
        self.assertIn("больше нуля", last_text(await self.send(ADMIN_ID, "-2")))
        await self.send(ADMIN_ID, "5")
        self.assertEqual(self.db.get_freezer_product("Филадельфия")["quantity"], 5)

    async def test_old_button_after_everything_defrosted(self):
        await self.click(ADMIN_ID, "defrost_count_2_2")
        requests = await self.click(ADMIN_ID, "defrost_count_2_1")
        self.assertIn("уже нет в морозильнике", last_text(requests))
        self.assertEqual(len(self.db.fridge_batches_list()), 1)

    async def test_empty_freezer(self):
        await self.click(ADMIN_ID, "defrost_count_2_2")
        await self.click(ADMIN_ID, "defrost_input_1")
        await self.send(ADMIN_ID, "10")
        self.assertIn("нет продуктов", last_text(await self.click(ADMIN_ID, "defrost_page_1")))

    async def test_search(self):
        await self.click(ADMIN_ID, "defrost_search")
        requests = await self.send(ADMIN_ID, "ФИЛ")
        self.assertIn("defrost_product_1", callbacks(requests))
        self.assertNotIn("defrost_product_2", callbacks(requests))


class WriteOffTest(BotTestCase):
    def setUp(self):
        super().setUp()
        self.db.new_product("Филадельфия", 2)
        self.db.new_product("Лосось", 3)
        self.db.new_delivery("Филадельфия", 20)
        self.db.new_delivery("Лосось", 20)
        self.db.move_to_fridge("Филадельфия", 5)  # партия 1
        self.db.move_to_fridge("Лосось", 4)       # партия 2
        self.db.move_to_fridge("Филадельфия", 1)  # партия 3
        self.skip_daily_notification(ADMIN_ID)

    def batch_quantity(self, batch_id):
        batch = self.db.get_fridge_batch(batch_id)
        return None if batch is None else batch["quantity"]

    async def test_list_marks_expired_and_today(self):
        self.set_expiration(1, -2)
        self.set_expiration(2, 0)
        requests = await self.click(ADMIN_ID, "batch_page_1")
        labels = button_texts(requests)
        self.assertTrue(labels[0].startswith("❌ Филадельфия — 5 шт."))
        self.assertTrue(labels[1].startswith("⚠️ Лосось — 4 шт."))
        self.assertIn("просрочено", last_text(requests))

    async def test_write_off_with_reason(self):
        requests = await self.click(ADMIN_ID, "batch_select_1")
        self.assertEqual(callbacks(requests)[:2], ["batch_writeoff_1", "batch_sale_1"])
        self.assertIn("batch_reason_1_other", callbacks(await self.click(ADMIN_ID, "batch_writeoff_1")))

        await self.click(ADMIN_ID, "batch_reason_1_damaged")
        self.assertIn("больше нуля", last_text(await self.send(ADMIN_ID, "abc")))
        self.assertIn("только 5", last_text(await self.send(ADMIN_ID, "9")))
        requests = await self.send(ADMIN_ID, "2")

        self.assertIn("Причина: Повреждено", last_text(requests))
        self.assertEqual(self.batch_quantity(1), 3)
        self.assertEqual(self.db.write_off_history()[1][0]["reason"], "Повреждено")

    async def test_other_reason_and_whole_batch(self):
        await self.click(ADMIN_ID, "batch_reason_1_other")
        requests = await self.send(ADMIN_ID, "Уронили <на пол>")
        self.assertIn("Уронили &lt;на пол&gt;", last_text(requests))

        requests = await self.click(ADMIN_ID, "batch_all_1")
        self.assertIn("Партия закрыта полностью", last_text(requests))
        self.assertIsNone(self.batch_quantity(1))
        self.assertEqual(self.db.write_off_history()[1][0]["reason"], "Уронили <на пол>")

    async def test_sale(self):
        await self.click(ADMIN_ID, "batch_sale_2")
        self.assertIn("Продано", last_text(await self.send(ADMIN_ID, "1")))
        self.assertEqual(self.batch_quantity(2), 3)
        self.assertEqual(self.db.write_off_history(), (0, None))

    async def test_whole_batch_button_from_old_message(self):
        await self.click(ADMIN_ID, "batch_sale_3")
        await self.click(ADMIN_ID, "batch_sale_2")  # теперь ввод идёт для партии 2

        requests = await self.click(ADMIN_ID, "batch_all_3")
        self.assertIn("устарела", alerts(requests)[0])
        self.assertEqual(self.batch_quantity(3), 1)

        await self.click(ADMIN_ID, "batch_all_2")
        self.assertIsNone(self.batch_quantity(2))

    async def test_search(self):
        await self.click(ADMIN_ID, "batch_search")
        requests = await self.send(ADMIN_ID, "ЛОС")
        self.assertIn("batch_select_2", callbacks(requests))
        self.assertNotIn("batch_select_1", callbacks(requests))


class ExpiringStockHistoryTest(BotTestCase):
    def setUp(self):
        super().setUp()
        self.db.add_user(EMPLOYEE_ID, "Иван")
        self.db.new_product("Медовик", 3)
        self.db.new_product("Калифорния", 1)
        self.db.new_product("Лосось", 3)
        for name in ("Медовик", "Калифорния", "Лосось"):
            self.db.new_delivery(name, 10)
        self.db.move_to_fridge("Медовик", 3)     # партия 1 — просрочена
        self.db.move_to_fridge("Калифорния", 1)  # партия 2 — истекает сегодня
        self.db.move_to_fridge("Лосось", 4)      # партия 3 — годная
        self.set_expiration(1, -2)
        self.set_expiration(2, 0)
        self.skip_daily_notification(ADMIN_ID, EMPLOYEE_ID)

    async def test_expiring_and_write_off_everything(self):
        requests = await self.click(ADMIN_ID, "expiring")
        self.assertIn("Сегодня заканчивается срок годности", last_text(requests))
        self.assertIn("Калифорния — 1 шт", last_text(requests))
        self.assertIn("Медовик — 3 шт", last_text(requests))
        self.assertNotIn("Лосось", last_text(requests))

        self.assertIn("expiring_clear_yes", callbacks(await self.click(ADMIN_ID, "expiring_clear")))
        requests = await self.click(EMPLOYEE_ID, "expiring_clear_yes")
        self.assertIn("Списано просроченных партий: 2", last_text(requests))
        self.assertEqual([b["id"] for b in self.db.fridge_batches_list()], [3])

        self.assertIn("ни у одной партии", last_text(await self.click(ADMIN_ID, "expiring")))

    async def test_stock(self):
        text = last_text(await self.click(ADMIN_ID, "stock"))
        self.assertIn("Годные", text)
        self.assertIn("Срок истекает сегодня", text)
        self.assertIn("Просрочено", text)
        self.assertLess(text.index("Годные"), text.index("Просрочено"))

    async def test_history(self):
        self.assertIn("Списаний пока не было", last_text(await self.click(ADMIN_ID, "history_page_1")))
        self.db.clear_expired_product(id=3, quantity=1, user_id=EMPLOYEE_ID, reason="Для сотрудника")
        text = last_text(await self.click(ADMIN_ID, "history_page_1"))
        self.assertIn("Лосось — 1 шт.", text)
        self.assertIn("Для сотрудника", text)
        self.assertIn("Иван", text)


class UsersTest(BotTestCase):
    async def add_user(self, telegram_id, name, role):
        await self.click(ADMIN_ID, "user_add")
        await self.send(ADMIN_ID, str(telegram_id))
        await self.send(ADMIN_ID, name)
        return await self.click(ADMIN_ID, f"user_newrole_{role}")

    async def test_add_employee(self):
        await self.click(ADMIN_ID, "user_add")
        self.assertIn("это число", last_text(await self.send(ADMIN_ID, "abc")))
        await self.send(ADMIN_ID, str(EMPLOYEE_ID))
        requests = await self.send(ADMIN_ID, "  Иван   Петров ")
        self.assertIn("<b>Иван Петров</b>", last_text(requests))

        requests = await self.click(ADMIN_ID, "user_newrole_employee")
        self.assertIn("Сотруднику отправлено уведомление", last_text(requests))
        self.assertIn("открыт доступ", sent_to(requests, EMPLOYEE_ID)[0])
        user = self.db.get_user(EMPLOYEE_ID)
        self.assertEqual((user["full_name"], user["role"], user["is_active"]), ("Иван Петров", "employee", True))

    async def test_notice_not_delivered(self):
        self.telegram.session.blocked_users.add(777)
        requests = await self.add_user(777, "Анна", "admin")
        self.assertIn("не доставлено", last_text(requests))
        self.assertEqual(self.db.get_user(777)["role"], "admin")

    async def test_existing_id(self):
        self.db.add_user(EMPLOYEE_ID, "Иван")
        await self.click(ADMIN_ID, "user_add")
        requests = await self.send(ADMIN_ID, str(EMPLOYEE_ID))
        self.assertIn("уже есть", last_text(requests))
        self.assertIn(f"user_view_{EMPLOYEE_ID}", callbacks(requests))

    async def test_role_and_access(self):
        self.db.add_user(EMPLOYEE_ID, "Иван")
        await self.click(ADMIN_ID, f"user_admin_{EMPLOYEE_ID}")
        self.assertEqual(self.db.get_user(EMPLOYEE_ID)["role"], "admin")
        await self.click(ADMIN_ID, f"user_employee_{EMPLOYEE_ID}")
        self.assertEqual(self.db.get_user(EMPLOYEE_ID)["role"], "employee")

        requests = await self.click(ADMIN_ID, f"user_disable_{EMPLOYEE_ID}")
        self.assertIn(f"user_enable_{EMPLOYEE_ID}", callbacks(requests))
        self.assertFalse(self.db.get_user(EMPLOYEE_ID)["is_active"])
        await self.click(ADMIN_ID, f"user_enable_{EMPLOYEE_ID}")
        self.assertTrue(self.db.get_user(EMPLOYEE_ID)["is_active"])

    async def test_cannot_change_yourself(self):
        self.db.add_user(777, "Анна", "admin")
        requests = await self.click(777, "user_view_777")
        self.assertIn("Это вы", last_text(requests))
        self.assertNotIn("user_disable_777", callbacks(requests))

        requests = await self.click(777, "user_disable_777")
        self.assertIn("Нельзя менять", alerts(requests)[0])
        self.assertTrue(self.db.get_user(777)["is_active"])


class ErrorsTest(BotTestCase):
    async def test_error_is_reported_and_saved(self):
        with mock.patch.object(self.db, "fridge_batches_list", side_effect=ZeroDivisionError):
            requests = await self.click(ADMIN_ID, "stock")

        self.assertIn("Что-то пошло не так", last_text(requests))
        with self.db.cursor() as cursor:
            cursor.execute("SELECT error_type FROM errors")
            self.assertEqual([row["error_type"] for row in cursor.fetchall()], ["ZeroDivisionError"])


if __name__ == "__main__":
    unittest.main()
