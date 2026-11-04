import copy
import unittest

from sample_project.orders import list_orders


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.orders = [{"id": i, "status": "paid"} for i in range(1, 6)]

    def test_default_page_and_input_order(self):
        self.assertEqual([x["id"] for x in list_orders(self.orders)], [1, 2])

    def test_second_page(self):
        result = list_orders(self.orders, page=2, page_size=2)
        self.assertEqual([x["id"] for x in result], [3, 4])

    def test_empty_and_beyond_end(self):
        self.assertEqual(list_orders([]), [])
        self.assertEqual(list_orders(self.orders, page=4), [])

    def test_rejects_invalid_pagination(self):
        for key in ("page", "page_size"):
            for value in (0, -1, True, 1.5, "2", None):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        list_orders(self.orders, **{key: value})

    def test_input_is_preserved_and_results_are_copies(self):
        before = copy.deepcopy(self.orders)
        result = list_orders(self.orders)
        self.assertEqual(self.orders, before)
        result[0]["status"] = "changed"
        self.assertEqual(self.orders, before)


if __name__ == "__main__":
    unittest.main()
