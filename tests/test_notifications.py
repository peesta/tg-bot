"""Уведомление после первого за день действия пользователя."""
import asyncio
import unittest
from unittest import mock

from tests.helpers import ADMIN_ID, BotSimulator, BotTestCase, ERROR_TEXT, sent_to


EMPLOYEE_ID = 555
NOTIFICATION = "Сегодня заканчивается срок годности"


def notifications(requests, user_id) -> list[str]:
    return [
        text for text in sent_to(requests, user_id)
        if NOTIFICATION in text or "Срок годности уже истёк" in text
    ]


class DailyNotificationTest(BotTestCase):
    def setUp(self):
        super().setUp()
        self.db.add_user(EMPLOYEE_ID, "Иван")
        self.db.new_product("Медовик", 1)
        self.db.new_delivery("Медовик", 10)
        self.db.move_to_fridge("Медовик", 2)
        self.set_expiration(1, 0)  # срок истекает сегодня

    async def test_after_first_command_of_the_day(self):
        requests = await self.send(EMPLOYEE_ID, "/start")
        messages = sent_to(requests, EMPLOYEE_ID)
        self.assertEqual(len(messages), 2)
        self.assertIn("Выберите действие", messages[0])  # сначала ответ на команду
        self.assertIn(NOTIFICATION, messages[1])
        self.assertIn("Медовик — 2 шт", messages[1])

    async def test_only_once_a_day(self):
        await self.send(EMPLOYEE_ID, "/start")
        requests = await self.click(EMPLOYEE_ID, "stock")
        requests += await self.send(EMPLOYEE_ID, "/menu")
        self.assertEqual(notifications(requests, EMPLOYEE_ID), [])

    async def test_button_counts_and_each_user_gets_own(self):
        requests = await self.click(ADMIN_ID, "batch_page_1")
        self.assertEqual(len(notifications(requests, ADMIN_ID)), 1)
        self.assertEqual(notifications(requests, EMPLOYEE_ID), [])

    async def test_again_next_day(self):
        await self.send(EMPLOYEE_ID, "/start")
        with self.db.cursor() as cursor:
            cursor.execute(
                "UPDATE daily_notifications "
                "SET last_date = date('now', 'localtime', '-1 day')"
            )
        requests = await self.click(EMPLOYEE_ID, "stock")
        self.assertEqual(len(notifications(requests, EMPLOYEE_ID)), 1)

    async def test_not_repeated_after_restart(self):
        await self.send(EMPLOYEE_ID, "/start")
        restarted = BotSimulator(self.db, admin_ids=frozenset({ADMIN_ID}))
        requests = await restarted.send(EMPLOYEE_ID, "/start")
        self.assertEqual(notifications(requests, EMPLOYEE_ID), [])

    async def test_no_access_no_notification(self):
        self.db.add_user(556, "Отключённый")
        self.db.set_user_active(556, False)
        requests = await self.send(99, "/start")
        requests += await self.send(556, "/start")
        self.assertEqual(notifications(requests, 99) + notifications(requests, 556), [])

        # Доступ вернули — уведомление приходит в тот же день.
        self.db.set_user_active(556, True)
        self.assertEqual(len(notifications(await self.send(556, "/start"), 556)), 1)

    async def test_not_duplicated_when_expiring_screen_opened_first(self):
        requests = await self.click(EMPLOYEE_ID, "expiring")
        requests += await self.click(EMPLOYEE_ID, "stock")
        self.assertEqual(notifications(requests, EMPLOYEE_ID), [])

    async def test_nothing_to_report(self):
        self.db.clear_expired_product()
        requests = await self.send(EMPLOYEE_ID, "/start")
        self.assertEqual(len(sent_to(requests, EMPLOYEE_ID)), 1)

    async def test_expired_batches_are_listed(self):
        self.set_expiration(1, -2)
        requests = await self.send(EMPLOYEE_ID, "/start")
        self.assertIn("Срок годности уже истёк", notifications(requests, EMPLOYEE_ID)[0])

    async def test_sent_even_if_handler_failed(self):
        with mock.patch.object(self.db, "fridge_batches_list", side_effect=ZeroDivisionError):
            requests = await self.click(EMPLOYEE_ID, "stock")
        messages = sent_to(requests, EMPLOYEE_ID)
        self.assertTrue(any(NOTIFICATION in text for text in messages))
        self.assertTrue(any(ERROR_TEXT in text for text in messages))

    async def test_blocked_user_does_not_break_bot(self):
        self.telegram.session.blocked_users.add(EMPLOYEE_ID)
        await self.send(EMPLOYEE_ID, "/start")  # не должно бросить исключение

    async def test_two_simultaneous_clicks_one_notification(self):
        results = await asyncio.gather(
            self.click(EMPLOYEE_ID, "stock"),
            self.click(EMPLOYEE_ID, "batch_page_1"),
        )
        requests = [request for result in results for request in result]
        self.assertEqual(len(notifications(self.telegram.session.requests, EMPLOYEE_ID)), 1)
        self.assertTrue(requests)


if __name__ == "__main__":
    unittest.main()
