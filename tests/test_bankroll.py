import unittest

from bankroll import calculate_bankroll, ledger_balance, rebase_ledger, settlement


class BankrollTests(unittest.TestCase):
    def test_users_example_counts_all_seven_stakes(self):
        self.assertEqual(settlement(10, 9.9, True), {"total_stake": 70.0, "returned": 99.0, "net": 29.0})
        self.assertEqual(settlement(10, 9.9, False), {"total_stake": 70.0, "returned": 0.0, "net": -70.0})
        result = calculate_bankroll(10, 9.9)
        self.assertEqual(result["stake_per_digit"], 10)
        self.assertEqual(result["total_stake"], 70)
        self.assertEqual(result["returned_if_hit"], 99)
        self.assertEqual(result["net_if_hit"], 29)
        self.assertEqual(result["net_if_miss"], -70)

    def test_small_and_fractional_stakes_are_used_as_entered(self):
        for stake, total, returned, net in ((1, 7, 9.9, 2.9), (2, 14, 19.8, 5.8),
                                           (2.5, 17.5, 24.75, 7.25), (0.01, 0.07, 0.09, 0.02)):
            with self.subTest(stake=stake):
                result = calculate_bankroll(stake, 9.9)
                self.assertEqual(result["stake_per_digit"], stake)
                self.assertEqual(result["total_stake"], total)
                self.assertEqual(result["returned_if_hit"], returned)
                self.assertEqual(result["net_if_hit"], net)

    def test_simulated_balance_does_not_change_or_zero_the_entered_stake(self):
        for balance in (1000, 900, 890, 1100, 1120, 0, -400):
            with self.subTest(balance=balance):
                result = calculate_bankroll(200, 9.9, balance=balance)
                self.assertEqual(result["balance"], balance)
                self.assertEqual(result["stake_per_digit"], 200)
                self.assertEqual(result["total_stake"], 1400)
                self.assertEqual(result["net_if_hit"], 580)
                self.assertEqual(result["net_if_miss"], -1400)

    def test_payout_at_or_below_break_even_still_calculates(self):
        for payout, net in ((7, 0), (5, -20)):
            result = calculate_bankroll(10, payout)
            self.assertEqual(result["stake_per_digit"], 10)
            self.assertEqual(result["total_stake"], 70)
            self.assertEqual(result["net_if_hit"], net)

    def test_ledger_keeps_saved_amounts_and_can_represent_a_negative_simulation(self):
        rows = [{"กำไร/ขาดทุนจำลอง": 5.8}, {"กำไร/ขาดทุนจำลอง": -14}, {"ผลตรวจ": "เข้า"}]
        self.assertEqual(ledger_balance(rows), 991.8)
        self.assertEqual(ledger_balance(rows[:1]), 1005.8)
        self.assertEqual(ledger_balance([{"กำไร/ขาดทุนจำลอง": -1400}]), -400)

    def test_invalid_parameters(self):
        for stake, payout in ((1, 0), (0, 9.9), (-1, 9.9), (0.001, 9.9),
                              (1, float("nan")), (float("inf"), 9.9)):
            with self.subTest(stake=stake, payout=payout), self.assertRaises(ValueError):
                calculate_bankroll(stake, payout)
        with self.assertRaises(ValueError):
            calculate_bankroll(10, 9.9, balance=float("nan"))

    def test_configurable_initial_capital_and_rebased_running_balances(self):
        rows = [{"กำไร/ขาดทุนจำลอง": 29, "ยอดคงเหลือจำลอง": 1029, "เงินต่อเลขจำลอง": 10},
                {"ผลตรวจ": "เข้า"},
                {"กำไร/ขาดทุนจำลอง": -70, "ยอดคงเหลือจำลอง": 959, "เงินต่อเลขจำลอง": 10}]
        rebased = rebase_ledger(rows, 2500.50)
        self.assertEqual(rebased[0]["ยอดคงเหลือจำลอง"], 2529.50)
        self.assertEqual(rebased[-1]["ยอดคงเหลือจำลอง"], 2459.50)
        self.assertEqual(ledger_balance(rows, 2500.50), 2459.50)
        self.assertEqual(rebased[-1]["เงินต่อเลขจำลอง"], 10)
        self.assertEqual(rebased[-1]["กำไร/ขาดทุนจำลอง"], -70)
        self.assertEqual(rows[-1]["ยอดคงเหลือจำลอง"], 959)
        self.assertEqual(rebased[1], rows[1])
        for capital in (0, 2500.50):
            plan = calculate_bankroll(10, 9.9, initial_capital=capital)
            self.assertEqual(plan["initial_capital"], capital)
            self.assertEqual(plan["balance"], capital)
        for capital in (-1, 0.001, float("nan"), float("inf")):
            with self.subTest(capital=capital), self.assertRaises(ValueError):
                calculate_bankroll(10, 9.9, initial_capital=capital)


if __name__ == "__main__":
    unittest.main()
