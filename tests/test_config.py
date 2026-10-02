"""Чтение настроек из .env в main.py."""
import os
import unittest
from unittest import mock

import main


class ConfigTest(unittest.TestCase):
    def setUp(self):
        # Настоящий .env на компьютере не должен влиять на тесты.
        patcher = mock.patch.object(main, "load_dotenv")
        patcher.start()
        self.addCleanup(patcher.stop)

    def env(self, **values):
        return mock.patch.dict(os.environ, values, clear=True)

    def test_telegram_key(self):
        with self.env(TELEGRAM_KEY=" 123456789:AAHtest "):
            self.assertEqual(main.get_bot_token(), "123456789:AAHtest")

    def test_telegram_key_missing(self):
        with self.env():
            with self.assertRaisesRegex(RuntimeError, "TELEGRAM_KEY не задана"):
                main.get_bot_token()

    def test_telegram_key_malformed(self):
        for value in ("abc", "123456789", "123:abc def", '"123:abc"'):
            with self.env(TELEGRAM_KEY=value):
                with self.assertRaisesRegex(RuntimeError, "не похож на токен"):
                    main.get_bot_token()

    def test_admin_ids(self):
        with self.env(ADMIN_IDS=" 1, 22 ,,333 "):
            self.assertEqual(main.get_admin_ids(), frozenset({1, 22, 333}))
        with self.env():
            self.assertEqual(main.get_admin_ids(), frozenset())
        with self.env(ADMIN_IDS="1,abc"):
            with self.assertRaises(RuntimeError):
                main.get_admin_ids()

    def test_google_table(self):
        with self.env(GOOGLE_TABLE="  "):
            self.assertIsNone(main.get_google_table())
        with self.env(GOOGLE_TABLE="https://docs.google.com/spreadsheets/d/KEY/edit"):
            self.assertEqual(main.get_google_table(), "https://docs.google.com/spreadsheets/d/KEY/edit")


if __name__ == "__main__":
    unittest.main()
