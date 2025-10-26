import json
import tempfile
import unittest
from datetime import datetime, timezone

from aistock.idempotency import OrderIdempotencyTracker


class IdempotencyTests(unittest.TestCase):
    def test_generate_client_order_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = OrderIdempotencyTracker(f"{tmpdir}/orders.json")
            timestamp = datetime(2024, 7, 9, 14, 30, tzinfo=timezone.utc)
            client_id = tracker.generate_client_order_id("AAPL", timestamp, "12.5")
            duplicate = tracker.generate_client_order_id("AAPL", timestamp, "12.5")
            different_qty = tracker.generate_client_order_id("AAPL", timestamp, "-3")

            self.assertEqual(client_id, duplicate)
            self.assertNotEqual(client_id, different_qty)

            self.assertTrue(client_id.startswith("AAPL_"))
            parts = client_id.split("_")
            self.assertEqual(len(parts), 3)
            self.assertTrue(parts[1].isdigit())  # Timestamp component is numeric
            self.assertEqual(len(parts[2]), 12)  # Truncated hash suffix

    def test_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = OrderIdempotencyTracker(f"{tmpdir}/orders.json")
            timestamp = datetime(2024, 7, 9, 14, 30, tzinfo=timezone.utc)
            client_id = tracker.generate_client_order_id("AAPL", timestamp, "5")

            self.assertFalse(tracker.is_duplicate(client_id))
            tracker.mark_submitted(client_id)
            self.assertTrue(tracker.is_duplicate(client_id))

    def test_persistence_across_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = f"{tmpdir}/orders.json"

            # First tracker submits order
            tracker1 = OrderIdempotencyTracker(storage_path)
            timestamp = datetime(2024, 7, 9, 14, 30, tzinfo=timezone.utc)
            client_id = tracker1.generate_client_order_id("AAPL", timestamp, 1)
            tracker1.mark_submitted(client_id)

            # Second tracker (simulating restart) should see the same order
            tracker2 = OrderIdempotencyTracker(storage_path)
            self.assertTrue(tracker2.is_duplicate(client_id))

    def test_clear_old_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = f"{tmpdir}/orders.json"
            tracker = OrderIdempotencyTracker(storage_path)

            # Submit 15 orders
            for i in range(15):
                timestamp = datetime(2024, 7, 9, 14, 30 + i, tzinfo=timezone.utc)
                client_id = tracker.generate_client_order_id("AAPL", timestamp, i)
                tracker.mark_submitted(client_id)

            self.assertEqual(tracker.count_submitted(), 15)

            # Clear to keep only 10
            tracker.clear_old_ids(retention_count=10)
            self.assertEqual(tracker.count_submitted(), 10)

            # Ensure the oldest entries were removed
            with open(storage_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            entries = payload["submitted_ids"]
            timestamp_values = sorted(entry["timestamp_ms"] for entry in entries)
            self.assertEqual(len(timestamp_values), 10)
            expected_earliest = int(datetime(2024, 7, 9, 14, 35, tzinfo=timezone.utc).timestamp() * 1000)
            self.assertGreaterEqual(timestamp_values[0], expected_earliest)

    def test_loads_legacy_v1_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = f"{tmpdir}/orders.json"
            timestamp = datetime(2024, 7, 9, 14, 30, tzinfo=timezone.utc)
            legacy_id = "AAPL_1720535400000_deadbeef"

            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"submitted_ids": [legacy_id]}, handle)

            tracker = OrderIdempotencyTracker(path)
            self.assertTrue(tracker.is_duplicate(legacy_id))
            # Newly generated ID should match deterministic format
            new_id = tracker.generate_client_order_id("AAPL", timestamp, 1)
            self.assertTrue(new_id.startswith("AAPL_"))


if __name__ == "__main__":
    unittest.main()
