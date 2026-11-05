import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from admin_store import AccessDenied, LoginLimited, SettingsStore, MAX_FAILURES

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "test-administrator"
MEMBER = "test-member-code"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.db"
        self.store = SettingsStore(self.path)
        self.store.bootstrap(ADMIN, MEMBER)
        self.admin = self.store.login(ADMIN)

    def test_only_admin_can_change_settings_and_passwords(self):
        member = self.store.login(MEMBER)
        for ticket in (None, member, {**member, "role": "admin"}):
            with self.assertRaises(AccessDenied):
                self.store.save_ai(ticket, "fake-key", "fake-model")
            with self.assertRaises(AccessDenied):
                self.store.change_password(ticket, "admin", "changed-admin")
            with self.assertRaises(AccessDenied):
                self.store.summary(ticket)

    def test_password_change_revokes_old_sessions_and_password_but_not_other_role(self):
        member = self.store.login(MEMBER)
        self.store.change_password(self.admin, "member", "replacement-member")
        self.assertIsNone(self.store.role(member))
        self.assertIsNone(self.store.login(MEMBER))
        self.assertEqual(self.store.login("replacement-member")["role"], "member")
        self.assertEqual(self.store.role(self.admin), "admin")
        self.store.change_password(self.admin, "admin", "replacement-admin")
        with self.assertRaises(AccessDenied):
            self.store.save_ai(self.admin, "key", "model")
        self.assertIsNone(self.store.login(ADMIN))

    def test_saved_values_survive_reopen_and_do_not_get_overwritten_by_bootstrap(self):
        self.store.save_ai(self.admin, "server-key", "model-a")
        self.store.change_password(self.admin, "member", "saved-member")
        reopened = SettingsStore(self.path)
        self.assertFalse(reopened.bootstrap("other-admin", "other-member", "other-key", "other-model"))
        self.assertEqual(reopened.ai_credentials(self.admin), ("server-key", "model-a"))
        self.assertIsNotNone(reopened.login("saved-member"))
        self.assertIsNone(reopened.login("other-member"))

    def test_blank_key_preserves_existing_and_clear_does_not_restore_secret(self):
        self.store.save_ai(self.admin, "key-original", "model-a")
        self.store.save_ai(self.admin, "", "model-b")
        self.assertEqual(self.store.ai_credentials(self.admin), ("key-original", "model-b"))
        self.store.save_ai(self.admin, "", "model-b", clear_key=True)
        self.store.bootstrap(ADMIN, MEMBER, "original-secret", "model-a")
        self.assertEqual(self.store.ai_credentials(self.admin), ("", "model-b"))

    def test_passwords_are_hashed_and_duplicate_roles_rejected(self):
        data = self.path.read_bytes()
        self.assertNotIn(ADMIN.encode(), data)
        self.assertNotIn(MEMBER.encode(), data)
        for role, password in (("admin", MEMBER), ("member", ADMIN), ("member", "1234")):
            with self.assertRaises(ValueError):
                self.store.change_password(self.admin, role, password)

    def test_login_throttle_survives_reconnect_then_expires(self):
        with patch("admin_store.time.time", return_value=1000):
            for _ in range(MAX_FAILURES):
                self.assertIsNone(self.store.login("wrong"))
            with self.assertRaises(LoginLimited):
                SettingsStore(self.path).login(ADMIN)
        with patch("admin_store.time.time", return_value=1061):
            self.assertEqual(self.store.login(ADMIN)["role"], "admin")

    def test_expired_ticket_and_recovery_revoke_access(self):
        with patch("admin_store.time.time", return_value=self.admin["expires"] + 1):
            self.assertIsNone(self.store.role(self.admin))
        self.store.reset_admin_locally("recovered-admin")
        self.assertIsNone(self.store.role(self.admin))
        self.assertEqual(self.store.login("recovered-admin")["role"], "admin")


class AccessUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "settings.db")

    @staticmethod
    def button(app, label):
        return next(item for item in app.button if item.label == label)

    def start(self, configured=True):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        app.secrets.update({"ZANI_SETTINGS_DB": self.path, "ADMIN_PASSWORD": ADMIN if configured else "",
                           "APP_PASSWORD": MEMBER if configured else "", "GOOGLE_API_KEY": "", "GEMINI_MODEL": ""})
        app.run()
        self.assertEqual(list(app.exception), [])
        return app

    def login(self, app, password):
        app.text_input(key="login_password").set_value(password)
        self.button(app, "เข้าสู่ระบบ →").click().run()
        self.assertEqual(list(app.exception), [])
        return app

    def test_anonymous_and_unconfigured_users_cannot_reach_app_or_setup(self):
        app = self.start(configured=False)
        self.assertEqual(len(app.text_input), 0)
        self.assertFalse(any(b.label == "ยืนยันประวัติ" for b in app.button))
        app = self.start()
        self.assertEqual([field.label for field in app.text_input], ["รหัสผ่าน"])
        self.login(app, "wrong-password")
        self.assertEqual(app.error[0].value, "รหัสผ่านไม่ถูกต้อง")
        self.assertFalse(any(b.label == "ยืนยันประวัติ" for b in app.button))

    def test_member_has_no_admin_or_api_inputs_even_with_admin_page_state(self):
        app = self.login(self.start(), MEMBER)
        self.assertEqual(len(app.text_input), 0)
        self.assertFalse(any(b.label == "หลังบ้าน" for b in app.button))
        app.session_state["active_page"] = "admin"
        app.run()
        self.assertEqual(len(app.text_input), 0)
        self.assertTrue(any(b.label == "ยืนยันประวัติ" for b in app.button))
        self.button(app, "ออกจากระบบ").click().run()
        self.assertEqual([field.label for field in app.text_input], ["รหัสผ่าน"])
        self.assertNotIn("history", app.session_state)

    def test_admin_saves_key_without_echoing_it_and_new_session_reads_saved_model(self):
        app = self.login(self.start(), ADMIN)
        app.text_input(key="admin_api_key").set_value("private-test-key")
        app.text_input(key="admin_model").set_value("test-model")
        self.button(app, "บันทึกการตั้งค่า AI").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.text_input(key="admin_api_key").value, "")
        self.assertEqual(app.text_input(key="admin_model").value, "test-model")
        store = SettingsStore(self.path)
        self.assertEqual(store.ai_credentials(app.session_state["access_ticket"]), ("private-test-key", "test-model"))
        member = self.login(self.start(), MEMBER)
        self.assertEqual(len(member.text_input), 0)
        self.assertTrue(member.toggle[0].value)
        rendered = " ".join(str(getattr(item, "proto", "")) for item in member)
        self.assertNotIn("private-test-key", rendered)

    def test_member_rotation_rejects_mismatch_then_logs_existing_member_out(self):
        member = self.login(self.start(), MEMBER)
        admin = self.login(self.start(), ADMIN)
        admin.text_input(key="new_member_password").set_value("next-member-code")
        admin.text_input(key="confirm_member_password").set_value("different-code")
        self.button(admin, "บันทึกรหัสสมาชิก").click().run()
        self.assertIn("ไม่ตรงกัน", admin.error[0].value)
        admin.text_input(key="new_member_password").set_value("next-member-code")
        admin.text_input(key="confirm_member_password").set_value("next-member-code")
        self.button(admin, "บันทึกรหัสสมาชิก").click().run()
        member.run()
        self.assertEqual([field.label for field in member.text_input], ["รหัสผ่าน"])
        self.assertNotIn("history", member.session_state)
        self.login(member, "next-member-code")
        self.assertTrue(any(b.label == "ยืนยันประวัติ" for b in member.button))

    def test_admin_password_change_requires_new_login(self):
        app = self.login(self.start(), ADMIN)
        app.text_input(key="new_admin_password").set_value("next-admin-code")
        app.text_input(key="confirm_admin_password").set_value("next-admin-code")
        self.button(app, "บันทึกรหัสผู้ดูแล").click().run()
        self.assertEqual([field.label for field in app.text_input], ["รหัสผ่าน"])
        self.login(app, "next-admin-code")
        self.assertTrue(any(title.value == "จัดการหลังบ้าน" for title in app.title))
        self.assertEqual(list(app.exception), [])


if __name__ == "__main__":
    unittest.main()
