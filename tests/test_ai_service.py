import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import httpx
from google.genai import errors, types
from pydantic import ValidationError

from ai_service import (ScanResult, Recommendation, _generate, ai_error_message,
                        choose_formula, prepare_image, scan_image, validate_scan)
from engine import SAMPLE_HISTORY, demo_formulas, rank_formulas


class VisionTests(unittest.TestCase):
    def test_columns_sorted_before_rows_and_repeats_preserved(self):
        result = validate_scan({"cells": [
            {"column": 1, "row": 0, "digit": 5, "confidence": 0.99},
            {"column": 0, "row": 1, "digit": 6, "confidence": 0.99},
            {"column": 1, "row": 1, "digit": 5, "confidence": 0.99},
            {"column": 0, "row": 0, "digit": 6, "confidence": 0.99}], "notes": []})
        self.assertEqual(result["text"], "6 6 5 5")
        self.assertEqual(result["warnings"], [])

    def test_unclear_cells_remain_visible_for_correction(self):
        result = validate_scan({"cells": [
            {"column": 0, "row": 0, "digit": None, "confidence": 0.1}], "notes": []})
        self.assertEqual(result["text"], "?")
        self.assertTrue(result["warnings"])

    def test_ten_and_zero_normalize_without_losing_repeats_or_unknown_cells(self):
        cells = [
            {"column": 2, "row": 1, "digit": None, "confidence": 0.2},
            {"column": 1, "row": 1, "digit": 5, "confidence": 0.99},
            {"column": 0, "row": 1, "digit": 0, "confidence": 0.99},
            {"column": 2, "row": 0, "digit": 10, "confidence": 0.99},
            {"column": 1, "row": 0, "digit": 5, "confidence": 0.99},
            {"column": 0, "row": 0, "digit": 10, "confidence": 0.99},
        ]
        result = validate_scan({"cells": cells, "notes": []})
        self.assertEqual(result["text"], "0 0 5 5 0 ?")
        self.assertEqual([cell["digit"] for cell in result["cells"]], [0, 0, 5, 5, 0, None])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("คอลัมน์ 3 แถว 2", result["warnings"][0])
        self.assertEqual(cells[-1]["digit"], 10)  # No mutation of the raw response.

    def test_duplicate_coordinates_rejected(self):
        cell = {"column": 0, "row": 0, "digit": 6, "confidence": 0.9}
        with self.assertRaises(ValueError):
            validate_scan({"cells": [cell, cell], "notes": []})

    def test_tiny_image_enlarged_and_invalid_file_rejected(self):
        source = io.BytesIO()
        Image.new("RGB", (293, 93), "white").save(source, format="PNG")
        output = prepare_image(source.getvalue())
        with Image.open(io.BytesIO(output)) as result:
            self.assertEqual(result.size, (1172, 372))
        with self.assertRaises(ValueError):
            prepare_image(b"not an image")

    @patch("ai_service._generate")
    def test_ai_cannot_select_nonexistent_formula(self, generate):
        ranked, _ = rank_formulas(demo_formulas(), SAMPLE_HISTORY)
        generate.return_value = {"formula_id": "invented", "reason": "test", "caution": "test"}
        with self.assertRaises(ValueError):
            choose_formula("test", "test", ranked, SAMPLE_HISTORY)

    @patch("google.genai._api_client.BaseApiClient.request")
    def test_actual_sdk_wire_payload_is_compatible_and_ocr_repeats_survive(self, request):
        cells = [{"column": col, "row": row, "digit": digit, "confidence": 0.99}
                 for col, digit in enumerate((6, 5)) for row in range(2)]
        scan = {"cells": cells, "notes": []}
        source = io.BytesIO()
        Image.new("RGB", (300, 200), "white").save(source, format="PNG")
        # Exercise the actual SDK serializer, not a mock of _generate. The old
        # payload contained additional_properties and large array bounds.
        def assert_shape(node):
            if isinstance(node, dict):
                forbidden = {"additional_properties", "additionalProperties", "maxItems", "max_items",
                             "maxLength", "max_length", "maximum", "minimum"}
                self.assertFalse(forbidden.intersection(node))
                for value in node.values():
                    assert_shape(value)
            elif isinstance(node, list):
                for value in node:
                    assert_shape(value)

        for schema, answer in ((ScanResult, scan),
                               (Recommendation, {"formula_id": "1", "reason": "test", "caution": "test"})):
            with self.subTest(schema=schema.__name__):
                request.return_value = types.HttpResponse(headers={}, body=json.dumps({
                    "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(answer)}]},
                                    "finishReason": "STOP"}]}))
                if schema is ScanResult:
                    result = scan_image("fake-key", "gemini-3.5-flash-lite", source.getvalue())
                    self.assertEqual(result["text"], "6 6 5 5")
                else:
                    self.assertEqual(_generate("fake-key", "gemini-3.5-flash-lite", "test", schema), answer)
                payload = request.call_args.args[2]
                config = payload["generationConfig"]
                self.assertEqual(config["responseMimeType"], "application/json")
                self.assertNotIn("temperature", config)
                wire_schema = config["responseSchema"]
                self.assertTrue(wire_schema["properties"])
                self.assertTrue(wire_schema["required"])
                assert_shape(wire_schema)

    def test_local_validation_remains_strict_after_wire_schema_is_simplified(self):
        cell = {"column": 0, "row": 0, "digit": 6, "confidence": 0.99}
        for changed in ({**cell, "digit": 11}, {**cell, "digit": "6"},
                        {**cell, "digit": "10"}, {**cell, "digit": 10.0}, {**cell, "digit": True},
                        {**cell, "column": -1}, {**cell, "confidence": 1.5},
                        {**cell, "unrequested": "extra"}):
            with self.subTest(cell=changed), self.assertRaises(ValidationError):
                validate_scan({"cells": [changed], "notes": []})
        with self.assertRaises(ValidationError):
            validate_scan({"cells": [cell] * 2001, "notes": []})

    def test_api_errors_have_actionable_codes_without_echoing_secrets(self):
        secret = "do-not-display-this-key"
        for code, tag in ((400, "AI-REQUEST-400"), (401, "AI-AUTH"), (403, "AI-AUTH"),
                          (404, "AI-MODEL-404"), (429, "AI-QUOTA-429"),
                          (402, "AI-BILLING-402"), (503, "AI-SERVER")):
            with self.subTest(code=code):
                error = errors.APIError(code, {"error": {"message": f"private request={secret}"}})
                message = ai_error_message(error)
                self.assertIn(tag, message)
                self.assertNotIn(secret, message)
        bad_key = errors.ClientError(400, {"error": {"message": f"API key invalid: {secret}"}})
        self.assertIn("AI-AUTH-400", ai_error_message(bad_key))
        self.assertNotIn(secret, ai_error_message(bad_key))

    def test_network_and_output_failures_are_classified_without_raw_data(self):
        for error, tag in ((httpx.ReadTimeout("secret"), "AI-TIMEOUT"),
                           (httpx.ConnectError("secret"), "AI-CONNECTION"),
                           (json.JSONDecodeError("secret", "secret", 0), "AI-OUTPUT"),
                           (RuntimeError("secret"), "AI-UNKNOWN")):
            with self.subTest(tag=tag):
                self.assertIn(tag, ai_error_message(error))
                self.assertNotIn("secret", ai_error_message(error))

    @patch("ai_service.random.uniform", return_value=0)
    @patch("ai_service.time.sleep")
    @patch("google.genai.models.Models.generate_content")
    def test_transient_errors_retry_then_return_valid_response_without_secret_logs(self, generate, sleep, jitter):
        answer = {"formula_id": "1", "reason": "test", "caution": "test"}
        generate.side_effect = [
            errors.ServerError(503, {"error": {"message": "key=private-test-key"}}),
            errors.ServerError(500, {"error": {"message": "private image payload"}}),
            SimpleNamespace(text=json.dumps(answer)),
        ]
        with self.assertLogs("ai_service", level="WARNING") as captured:
            result = _generate("private-test-key", "test-model", "test", Recommendation)
        self.assertEqual(result, answer)
        self.assertEqual(generate.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        logs = " ".join(captured.output)
        self.assertIn("http=503", logs)
        self.assertNotIn("private-test-key", logs)
        self.assertNotIn("private image payload", logs)

    @patch("ai_service.time.sleep")
    @patch("google.genai.models.Models.generate_content")
    def test_permanent_and_quota_errors_do_not_retry(self, generate, sleep):
        for code in (400, 401, 403, 404, 429, 501):
            with self.subTest(code=code):
                generate.reset_mock()
                generate.side_effect = errors.APIError(code, {"error": {"message": "test"}})
                with self.assertLogs("ai_service", level="WARNING"), self.assertRaises(errors.APIError):
                    _generate("test-key", "test-model", "test", Recommendation)
                self.assertEqual(generate.call_count, 1)
                sleep.assert_not_called()

    @patch("ai_service.time.sleep")
    @patch("google.genai.models.Models.generate_content")
    def test_persistent_server_error_stops_after_three_attempts(self, generate, sleep):
        generate.side_effect = errors.ServerError(503, {"error": {"message": "test"}})
        with self.assertLogs("ai_service", level="WARNING"), self.assertRaises(errors.ServerError) as raised:
            _generate("test-key", "test-model", "test", Recommendation)
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("AI-SERVER-503", ai_error_message(raised.exception))

    @patch("ai_service.time.monotonic", side_effect=[0, 0, 89])
    @patch("ai_service.time.sleep")
    @patch("google.genai.models.Models.generate_content")
    def test_time_budget_prevents_another_request(self, generate, sleep, monotonic):
        generate.side_effect = httpx.ReadTimeout("test")
        with self.assertLogs("ai_service", level="WARNING"), self.assertRaises(httpx.ReadTimeout):
            _generate("test-key", "test-model", "test", Recommendation)
        self.assertEqual(generate.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(generate.call_args.kwargs["config"].http_options.timeout, 45000)

    @patch("ai_service.time.sleep")
    @patch("google.genai.models.Models.generate_content")
    def test_connection_failure_can_recover_without_retrying_bad_json(self, generate, sleep):
        generate.side_effect = [httpx.ConnectError("test"), SimpleNamespace(text='{"ok": true}')]
        with self.assertLogs("ai_service", level="WARNING"):
            self.assertEqual(_generate("test-key", "test-model", "test", Recommendation), {"ok": True})
        self.assertEqual(generate.call_count, 2)
        generate.reset_mock()
        sleep.reset_mock()
        generate.side_effect = [SimpleNamespace(text="malformed")]
        with self.assertRaises(json.JSONDecodeError):
            _generate("test-key", "test-model", "test", Recommendation)
        self.assertEqual(generate.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
