import json
import unittest

from scripts.run_minimax_task import extract_code, final_response


class MiniMaxAdapterTests(unittest.TestCase):
    def setUp(self):
        self.source = "def list_orders(orders):\n    return list(orders)\n"

    def test_cli_parsed_business_json(self):
        response = final_response({"path": "sample_project/orders.py", "content": self.source})
        self.assertEqual(extract_code(response), self.source)

    def test_message_blocks_keep_final_content_only(self):
        payload = {"path": "sample_project/orders.py", "content": self.source}
        response = final_response({"model": "fixture", "content": [
            {"type": "thinking", "thinking": "synthetic excluded block"},
            {"type": "text", "text": json.dumps(payload)}]})
        self.assertEqual(extract_code(response), self.source)
        self.assertNotIn("synthetic excluded block", json.dumps(response))

    def test_unwrapped_source_and_disallowed_path(self):
        self.assertEqual(extract_code(final_response({"content": self.source})), self.source.strip())
        with self.assertRaises(ValueError):
            extract_code(final_response({"path": "tests/test_target.py", "content": self.source}))


if __name__ == "__main__":
    unittest.main()
