import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest

module_path = Path(os.environ["TICKET_MODULE"])
spec = importlib.util.spec_from_file_location("tickets_under_test", module_path)
tickets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets)
DATA = json.loads((Path(__file__).resolve().parents[1] / "data.json").read_text())

class TargetTests(unittest.TestCase):
    def test_open(self):
        self.assertEqual([r["id"] for r in tickets.list_tickets(DATA, "open")], [1, 2])
    def test_closed(self):
        self.assertEqual([r["id"] for r in tickets.list_tickets(DATA, "closed")], [3])
    def test_invalid(self):
        for value in ("", "OPEN", "pending", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tickets.list_tickets(DATA, value)
    def test_empty_invalid(self):
        with self.assertRaises(ValueError):
            tickets.list_tickets([], "pending")

class RegressionTests(unittest.TestCase):
    def test_default_order_and_fields(self):
        self.assertEqual(tickets.list_tickets(DATA), sorted(DATA, key=lambda r: r["id"]))
    def test_no_mutation(self):
        rows = copy.deepcopy(DATA)
        out = tickets.list_tickets(rows)
        out[0]["title"] = "changed"
        self.assertEqual(rows, DATA)
    def test_empty(self):
        for status in (None, "open", "closed"):
            self.assertEqual(tickets.list_tickets([], status), [])
    def test_filtered_fields(self):
        expected = dict(DATA[0])
        result = tickets.list_tickets([expected], "closed")
        self.assertEqual(result, [expected])
        self.assertIsNot(result[0], expected)

if __name__ == "__main__":
    unittest.main()
