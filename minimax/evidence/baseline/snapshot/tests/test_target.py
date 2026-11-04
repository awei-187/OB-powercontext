import copy
import unittest

from sample_project.orders import list_orders


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.orders = [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "paid"},
            {"id": 3, "status": "cancelled"},
            {"id": 4, "status": "paid"},
            {"id": 5, "status": "pending"},
            {"id": 6, "status": "paid"},
        ]

    def test_filter_precedes_pagination(self):
        result = list_orders(self.orders, status="paid", page=2, page_size=2)
        self.assertEqual([x["id"] for x in result], [6])

    def test_all_valid_statuses_preserve_order(self):
        for status, ids in (("paid", [2, 4, 6]), ("pending", [1, 5]), ("cancelled", [3])):
            with self.subTest(status=status):
                result = list_orders(self.orders, status=status, page_size=20)
                self.assertEqual([x["id"] for x in result], ids)

    def test_none_is_compatible(self):
        self.assertEqual(list_orders(self.orders, status=None), list_orders(self.orders))

    def test_no_matches(self):
        self.assertEqual(list_orders([{"id": 1, "status": "paid"}], status="pending"), [])
        self.assertEqual(list_orders([], status="paid"), [])

    def test_invalid_status_is_rejected(self):
        for status in ("", "PAID", " paid", "unknown", "refunded", True, 7, [], {}):
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    list_orders(self.orders, status=status)

    def test_filter_does_not_mutate_input(self):
        before = copy.deepcopy(self.orders)
        result = list_orders(self.orders, status="paid")
        self.assertEqual(self.orders, before)
        result[0]["status"] = "changed"
        self.assertEqual(self.orders, before)


if __name__ == "__main__":
    unittest.main()
