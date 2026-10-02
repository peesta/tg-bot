"""Чтение настроек из .env и команда set-password в main.py."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from storage.db import Database
from web.auth import check_password


class ConfigTest(unittest.TestCase):
    def setUp(self):
        # Настоящий .env на компьютере не должен влиять на тесты.
        patcher = mock.patch.object(main, "load_dotenv")
        patcher.start()
        self.addCleanup(patcher.stop)

    def env(self, **values):
        return mock.patch.dict(os.environ, values, clear=True)

    def test_defaults(self):
        with self.env():
            self.assertEqual(main.get_settings(), {
                "host": "127.0.0.1",
                "port": 8000,
                "secret_key": None,
                "google_table": None,
                "secure_cookies": False,
            })

    def test_values(self):
        with self.env(
            HOST=" 0.0.0.0 ", PORT="8080", SECRET_KEY=" abc ",
            GOOGLE_TABLE="https://docs.google.com/spreadsheets/d/KEY/edit",
            SECURE_COOKIES="Yes",
        ):
            settings = main.get_settings()
        self.assertEqual(settings["host"], "0.0.0.0")
        self.assertEqual(settings["port"], 8080)
        self.assertEqual(settings["secret_key"], "abc")
        self.assertEqual(settings["google_table"], "https://docs.google.com/spreadsheets/d/KEY/edit")
        self.assertTrue(settings["secure_cookies"])

    def test_bad_port(self):
        for value in ("abc", "0", "70000", "-1"):
            with self.env(PORT=value):
                with self.assertRaisesRegex(RuntimeError, "PORT"):
                    main.get_settings()


class SetPasswordTest(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.db_path = str(Path(temp_dir.name) / "test.db")
        self.db = Database(self.db_path)

    def set_password(self, username, *answers):
        with mock.patch.object(main.getpass, "getpass", side_effect=answers), \
                mock.patch("builtins.print"):
            main.set_password(username, self.db_path)

    def test_resets_password_and_enables_access(self):
        user_id = self.db.add_user("admin", "Админ", "old", "admin")
        self.db.set_user_active(user_id, False)

        self.set_password("ADMIN", "secret1", "secret1")

        user = self.db.get_user(user_id)
        self.assertTrue(check_password(user["password_hash"], "secret1"))
        self.assertTrue(user["is_active"])

    def test_creates_admin(self):
        self.set_password("boss", "secret1", "secret1")
        user = self.db.get_user_by_username("boss")
        self.assertEqual(user["role"], "admin")

    def test_rejects_short_or_mismatched(self):
        with self.assertRaises(SystemExit):
            self.set_password("boss", "123")
        with self.assertRaises(SystemExit):
            self.set_password("boss", "secret1", "secret2")
        self.assertIsNone(self.db.get_user_by_username("boss"))


if __name__ == "__main__":
    unittest.main()
