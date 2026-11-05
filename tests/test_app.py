import unittest
import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest
from engine import SAMPLE_HISTORY

ROOT = Path(__file__).resolve().parents[1]


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def button(self, app, label):
        return next(item for item in app.button if item.label == label)

    def enter_history(self, app):
        app.text_area(key="history_text").set_value(" ".join(map(str, SAMPLE_HISTORY))).run()
        self.button(app, "ยืนยันประวัติ").click().run()

    def start(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        app.secrets.update({"ZANI_SETTINGS_DB": str(Path(self.temp.name) / "settings.db"),
                            "ADMIN_PASSWORD": "test-admin-only", "APP_PASSWORD": "test-member-only",
                            "GOOGLE_API_KEY": "", "GEMINI_MODEL": ""})
        app.run()
        app.text_input(key="login_password").set_value("test-member-only")
        self.button(app, "เข้าสู่ระบบ →").click().run()
        self.assertEqual(list(app.exception), [])
        return app

    def test_real_library_sample_analysis_append_zero_and_undo(self):
        app = self.start()
        self.assertEqual([item.value for item in app.metric], ["—", "—", "—"])
        self.enter_history(app)
        self.assertEqual(len(app.session_state["history"]), 21)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(list(app.exception), [])
        analysis = app.session_state["analysis"]
        self.assertEqual(len(analysis["ranked"]), 108)
        self.assertEqual(len(analysis["plan"]), 20)
        chosen = analysis["chosen"]
        self.assertEqual([item.value for item in app.metric],
                         [f"{chosen['hits']}/{chosen['count']}", f"{chosen['rate']:.1%}", f"{chosen['max_losses']} งวด"])
        old_selection = analysis["plan"][0]["include"]
        app.button(key="actual_0").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["history"][-1], 0)
        self.assertIsNone(app.session_state["analysis"])
        self.assertEqual([item.value for item in app.metric], ["—", "—", "—"])
        self.assertEqual(app.session_state["live_log"][-1]["ผลตรวจ"], "เข้า" if 0 in old_selection else "ไม่เข้า")
        self.button(app, "↶ ย้อนกลับ 1 งวด").click().run()
        self.assertEqual(len(app.session_state["history"]), 21)
        self.assertEqual(app.session_state["live_log"], [])

    def test_edit_invalidates_report_and_requires_confirmation(self):
        app = self.start()
        self.enter_history(app)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        app.text_area(key="history_text").set_value("0 4 6").run()
        self.assertIsNone(app.session_state["analysis"])
        self.assertEqual([item.value for item in app.metric], ["—", "—", "—"])
        self.assertTrue(self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").disabled)
        self.button(app, "ยืนยันประวัติ").click().run()
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["analysis"]["history"], [0, 4, 6])

    def test_manual_ten_alias_confirms_and_analyzes_as_zero(self):
        app = self.start()
        app.text_area(key="history_text").set_value("10 0 6 10").run()
        self.button(app, "ยืนยันประวัติ").click().run()
        self.assertEqual(app.session_state["history"], [0, 0, 6, 0])
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["analysis"]["history"], [0, 0, 6, 0])
        self.assertTrue(any(item.value == "ผลงวดล่าสุด 0" for item in app.caption))

    def test_calculator_continues_after_negative_balance_with_fixed_payout(self):
        app = self.start()
        self.enter_history(app)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        app.number_input(key="money_unit").set_value(200.0)
        self.button(app, "บันทึก").click().run()
        missed_digit = app.session_state["analysis"]["plan"][0]["exclude"][0]
        app.button(key=f"actual_{missed_digit}").click().run()
        self.assertEqual(app.session_state["live_log"][-1]["กำไร/ขาดทุนจำลอง"], -1400)
        self.assertEqual(app.session_state["live_log"][-1]["ยอดคงเหลือจำลอง"], -400)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        result = app.session_state["analysis"]["money"]["plan"]
        self.assertEqual(result["balance"], -400)
        self.assertEqual(result["stake_per_digit"], 200)
        self.assertEqual(result["total_stake"], 1400)
        self.assertEqual(result["net_if_hit"], 580)
        self.assertEqual(result["gross_return"], 9.9)
        self.assertNotIn("money_gross", [item.key for item in app.number_input])
        self.assertEqual(app.session_state["live_log"][-1]["อัตราจ่ายรวมทุน"], 9.9)
        rendered = " ".join(item.value for item in [*app.markdown, *app.info, *app.caption])
        for removed in ("แนะนำพัก", "เงินลงที่แนะนำ", "งบอ้างอิง", "+-400"):
            self.assertNotIn(removed, rendered)
        self.assertIn("-400.00 บาท", rendered)
        self.assertEqual(list(app.exception), [])

    def test_money_panel_settings_ledger_and_undo(self):
        app = self.start()
        self.enter_history(app)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertFalse(any("มีข้อมูลทดสอบเพียง" in item.value for item in app.warning))
        plan = app.session_state["analysis"]["money"]["plan"]
        self.assertEqual(plan["gross_return"], 9.9)
        self.assertEqual(plan["stake_per_digit"], 1)
        app.number_input(key="money_unit").set_value(10.0)
        app.number_input(key="money_initial_capital").set_value(2500.50)
        # Draft values cannot change the calculation before an explicit save.
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["stake_per_digit"], 1)
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["initial_capital"], 1000)
        self.button(app, "บันทึก").click().run()
        configured_plan = app.session_state["analysis"]["money"]["plan"]
        self.assertEqual(configured_plan["initial_capital"], 2500.50)
        self.assertEqual(configured_plan["balance"], 2500.50)
        self.assertEqual(configured_plan["stake_per_digit"], 10)
        self.assertEqual(configured_plan["total_stake"], 70)
        self.assertEqual(configured_plan["net_if_hit"], 29)
        hit_digit = app.session_state["analysis"]["plan"][0]["include"][0]
        app.button(key=f"actual_{hit_digit}").click().run()
        self.assertEqual(app.session_state["live_log"][-1]["กำไร/ขาดทุนจำลอง"], 29)
        self.assertEqual(app.session_state["live_log"][-1]["ยอดคงเหลือจำลอง"], 2529.50)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["balance"], 2529.50)
        app.number_input(key="money_initial_capital").set_value(5000.0)
        app.number_input(key="money_unit").set_value(20.0)
        self.button(app, "บันทึก").click().run()
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["balance"], 5029)
        self.assertEqual(app.session_state["live_log"][-1]["ยอดคงเหลือจำลอง"], 5029)
        self.assertEqual(app.session_state["live_log"][-1]["เงินต่อเลขจำลอง"], 10)
        self.assertEqual(app.session_state["live_log"][-1]["กำไร/ขาดทุนจำลอง"], 29)
        hit_digit = app.session_state["analysis"]["plan"][0]["include"][0]
        app.button(key=f"actual_{hit_digit}").click().run()
        self.assertEqual(app.session_state["live_log"][-1]["ยอดคงเหลือจำลอง"], 5087)
        self.assertEqual(app.session_state["live_log"][-1]["เงินต่อเลขจำลอง"], 20)
        self.button(app, "↶ ย้อนกลับ 1 งวด").click().run()
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["balance"], 5029)
        self.button(app, "↶ ย้อนกลับ 1 งวด").click().run()
        self.assertEqual(app.session_state["live_log"], [])
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["balance"], 5000.0)
        # A new history resets the ledger but keeps the saved starting capital.
        self.enter_history(app)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["balance"], 5000.0)
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["stake_per_digit"], 20)
        self.assertEqual(list(app.exception), [])

    def test_invalid_money_settings_leave_saved_plan_and_ledger_unchanged(self):
        app = self.start()
        self.enter_history(app)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        original_plan = dict(app.session_state["analysis"]["money"]["plan"])
        app.number_input(key="money_initial_capital").set_value(123.456)
        app.number_input(key="money_unit").set_value(10.0)
        self.button(app, "บันทึก").click().run()
        self.assertTrue(app.error)
        self.assertEqual(app.session_state["money_settings"], {"initial_capital": 1000, "unit": 1})
        self.assertEqual(app.session_state["analysis"]["money"]["plan"], original_plan)
        self.assertEqual(app.session_state["live_log"], [])
        app.number_input(key="money_initial_capital").set_value(123.45)
        self.button(app, "บันทึก").click().run()
        self.assertEqual(list(app.error), [])
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["balance"], 123.45)
        self.assertEqual(list(app.exception), [])

    def test_money_menu_saves_before_analysis_and_updates_after_history_reset(self):
        app = self.start()
        app.number_input(key="money_initial_capital").set_value(2000.0)
        app.number_input(key="money_unit").set_value(10.0)
        self.button(app, "บันทึก").click().run()
        self.assertIsNone(app.session_state["analysis"])
        self.enter_history(app)
        self.button(app, "วิเคราะห์สูตรและคำนวณ 20 งวด →").click().run()
        self.assertEqual(app.session_state["analysis"]["money"]["plan"]["initial_capital"], 2000)
        hit_digit = app.session_state["analysis"]["plan"][0]["include"][0]
        app.button(key=f"actual_{hit_digit}").click().run()
        self.assertIsNone(app.session_state["analysis"])
        self.assertTrue(any("ยอดจำลองล่าสุด 2,029.00 บาท" in item.value for item in app.caption))
        self.enter_history(app)
        self.assertEqual(app.session_state["live_log"], [])
        self.assertTrue(any("ยอดจำลองล่าสุด 2,000.00 บาท" in item.value for item in app.caption))
        self.assertEqual(list(app.exception), [])


if __name__ == "__main__":
    unittest.main()
