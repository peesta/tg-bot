"""Чтение настроек из .env и команда set-password в main.py."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from storage.accounts import Accounts, check_password
from storage.db import Database


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
            HOST=" 0.0.0.0 ", PORT="8080", SECRET_KEY=" abc ", SECURE_COOKIES="Yes",
            GOOGLE_TABLE="https://docs.google.com/spreadsheets/d/KEY/edit",
        ):
            settings = main.get_settings()
        self.assertEqual(
            (settings["host"], settings["port"], settings["secret_key"], settings["secure_cookies"]),
            ("0.0.0.0", 8080, "abc", True),
        )
        self.assertEqual(settings["google_table"], "https://docs.google.com/spreadsheets/d/KEY/edit")

    def test_bad_port(self):
        for value in ("abc", "0", "70000", "-1"):
            with self.env(PORT=value):
                with self.assertRaisesRegex(RuntimeError, "PORT"):
                    main.get_settings()


class SiteLinksTest(unittest.TestCase):
    def test_local_only(self):
        self.assertEqual(main.site_links("127.0.0.1", 8000), ["http://127.0.0.1:8000"])

    def test_all_addresses_show_lan_link(self):
        with mock.patch.object(main, "local_ip", return_value="192.168.1.5"):
            links = main.site_links("0.0.0.0", 8080)
        self.assertEqual(links[0], "http://127.0.0.1:8080")
        self.assertTrue(links[1].startswith("http://192.168.1.5:8080"))

    def test_no_network(self):
        with mock.patch.object(main, "local_ip", return_value=None):
            self.assertEqual(main.site_links("0.0.0.0", 8000), ["http://127.0.0.1:8000"])


class SetPasswordTest(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.db_path = str(Path(temp_dir.name) / "test.db")
        self.db = Database(self.db_path)
        self.accounts = Accounts(self.db)

    def set_password(self, username, *answers):
        with mock.patch.object(main.getpass, "getpass", side_effect=answers), \
                mock.patch("builtins.print"):
            main.set_password(username, self.db_path)

    def test_resets_password_and_enables_access(self):
        self.accounts.create_defaults()
        self.db.set_user_active(1, False)

        self.set_password("ADMIN", "secret", "secret")

        user = self.accounts.get(1)
        self.assertTrue(check_password(user["password_hash"], "secret"))
        self.assertTrue(user["is_active"])

    def test_creates_admin(self):
        self.set_password("boss", "secret", "secret")
        self.assertEqual(self.accounts.get_by_username("boss")["role"], "admin")

    def test_rejects_short_or_mismatched(self):
        with self.assertRaises(SystemExit):
            self.set_password("boss", "12")
        with self.assertRaises(SystemExit):
            self.set_password("boss", "secret", "other")
        self.assertIsNone(self.accounts.get_by_username("boss"))


if __name__ == "__main__":
    unittest.main()
