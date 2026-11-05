import json
import unittest
from pathlib import Path

from engine import (SAMPLE_HISTORY, expression, formula_from_dict, make_plan,
                    parse_digits, rank_formulas, road_columns, selection)
from sheets import parse_matrix, parse_triple, spreadsheet_id

ROOT = Path(__file__).resolve().parents[1]


class FormulaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((ROOT / "data/formulas_snapshot.json").read_text(encoding="utf-8"))
        cls.formulas, cls.errors = parse_matrix(cls.snapshot["values"], "สูตร")

    def test_all_real_sheet_formulas_and_seed_complements(self):
        self.assertEqual(len(self.formulas), 108)
        self.assertEqual(self.errors, [])
        for formula in self.formulas:
            for seed in range(10):
                take, omit = selection(formula, [seed])
                self.assertEqual(len(take), 7)
                self.assertEqual(len(omit), 3)
                self.assertEqual(set(take) | set(omit), set(range(10)))
                self.assertFalse(set(take) & set(omit))

    def test_verified_sheet_cell_and_leading_zero(self):
        self.assertEqual(selection(self.formulas[0], [0])[1], [4, 5, 6])
        self.assertEqual(selection(self.formulas[2], [0])[1], [0, 5, 8])
        self.assertEqual(selection(self.formulas[0], [6])[1], [0, 1, 2])
        self.assertEqual(parse_triple(58), [0, 5, 8])

    def test_repeat_road_matches_attachment(self):
        self.assertEqual(road_columns(SAMPLE_HISTORY)[-4:], [[6, 6], [5, 5], [4], [8, 8, 8]])
        self.assertEqual([d for col in road_columns(SAMPLE_HISTORY) for d in col], SAMPLE_HISTORY)
        self.assertEqual(len(SAMPLE_HISTORY), 21)

    def test_walk_forward_does_not_use_actual_before_prediction(self):
        ranked, _ = rank_formulas([self.formulas[0]], [0, 4, 6])
        rows = ranked[0]["records"]
        # seed 0 excludes 456 => result 4 misses; seed 4 excludes 890 => result 6 hits.
        self.assertEqual([row["exclude"] for row in rows], [[4, 5, 6], [0, 8, 9]])
        self.assertEqual([row["hit"] for row in rows], [False, True])
        longer, _ = rank_formulas([self.formulas[0]], [0, 4, 6, 2, 3])
        self.assertEqual(longer[0]["records"][:2], rows)

    def test_all_formulas_share_evaluation_window(self):
        ranked, errors = rank_formulas(self.formulas, SAMPLE_HISTORY)
        self.assertEqual(len(ranked), 108)
        self.assertEqual(errors, [])
        self.assertEqual({row["count"] for row in ranked}, {20})
        self.assertEqual(sum(row["hit"] for row in ranked[0]["records"]), ranked[0]["hits"])

    def test_plan_is_twenty_and_scenario_is_not_observed_history(self):
        original = [0, 4, 6]
        plan = make_plan(self.formulas[0], original, scenario=[0] * 19)
        self.assertEqual(len(plan), 20)
        self.assertEqual(original, [0, 4, 6])
        self.assertEqual(plan[0]["exclude"], [0, 1, 2])
        self.assertEqual(plan[1]["exclude"], [4, 5, 6])
        self.assertEqual(plan[0]["basis"], "ประวัติจริง")
        self.assertTrue(all(row["basis"] == "ตามผลสมมติ" for row in plan[1:]))
        with self.assertRaises(ValueError):
            make_plan(self.formulas[0], original, scenario=[0] * 18)

    def test_malformed_history_not_silently_parsed(self):
        self.assertEqual(parse_digits("6 --> 6 → 5,5 0"), [6, 6, 5, 5, 0])
        for text in ("6 ? 5", "2026/11/04", "66", "1 hello 3", "1.2", "1,,2,", "11", "100", "010"):
            with self.assertRaises(ValueError, msg=text):
                parse_digits(text)

    def test_ten_alias_is_one_round_and_uses_the_zero_formula_seed(self):
        history = parse_digits("10 0 10,6 → 10")
        self.assertEqual(history, [0, 0, 0, 6, 0])
        self.assertEqual(road_columns(history), [[0, 0, 0], [6], [0]])
        self.assertEqual(selection(self.formulas[0], history), selection(self.formulas[0], [0]))
        self.assertEqual(parse_digits("1 0 10", limit=3), [1, 0, 0])
        with self.assertRaises(ValueError):
            parse_digits("10 10", limit=1)

    def test_bad_sheet_column_is_reported_not_repaired(self):
        rows = [row[:] for row in self.snapshot["values"]]
        rows[2][1] = "556"
        formulas, errors = parse_matrix(rows)
        self.assertEqual(len(formulas), 107)
        self.assertEqual(len(errors), 1)
        self.assertIn("B3", errors[0]["reason"])
        with self.assertRaises(ValueError):
            parse_matrix(rows[:-1])

    def test_server_fetch_url_is_restricted(self):
        for url in ("http://localhost/a", "https://docs.google.com.evil.test/spreadsheets/d/abcd",
                    "https://example.com/", "file:///secrets"):
            with self.assertRaises(ValueError):
                spreadsheet_id(url)
        self.assertEqual(spreadsheet_id(self.snapshot["source_url"]), self.snapshot["spreadsheet_id"])

    def test_arithmetic_does_not_execute_code(self):
        self.assertEqual(expression("(last + p2 * 2) % 10", [4, 7]), 5)
        for text in ("__import__('os').getcwd()", "last ** 1000000", "[1][0]", "n / 2", "2 % 0"):
            with self.assertRaises(ValueError):
                expression(text, [1, 2])


if __name__ == "__main__":
    unittest.main()
