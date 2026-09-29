import unittest

from sentinel import TelemetrySentinel, ThresholdRule


class SentinelTests(unittest.TestCase):
    def setUp(self):
        self.monitor = TelemetrySentinel([ThresholdRule("pressure_bar", 150, 140, consecutive=2)])
        self.now = 1000.0

    def event(self, event_id, sequence, value, timestamp=None):
        return {
            "event_id": event_id,
            "sensor_id": "line-1",
            "metric": "pressure_bar",
            "value": value,
            "sequence": sequence,
            "timestamp": self.now if timestamp is None else timestamp,
        }

    def test_alert_requires_consecutive_breaches_and_clears_with_hysteresis(self):
        first = self.monitor.ingest(self.event("a", 1, 151), self.now)
        second = self.monitor.ingest(self.event("b", 2, 153), self.now)
        self.assertFalse(first["alert_active"])
        self.assertTrue(second["alert_active"])
        self.monitor.ingest(self.event("c", 3, 135), self.now)
        self.assertEqual(self.monitor.snapshot()["active_alerts"], [])

    def test_duplicate_event_is_ignored(self):
        event = self.event("same", 1, 151)
        self.monitor.ingest(event, self.now)
        result = self.monitor.ingest(event, self.now)
        self.assertEqual(result["reason"], "duplicate_event")

    def test_out_of_order_sensor_sequence_is_rejected(self):
        self.monitor.ingest(self.event("a", 2, 151), self.now)
        with self.assertRaises(ValueError):
            self.monitor.ingest(self.event("b", 1, 152), self.now)

    def test_stale_event_is_rejected(self):
        with self.assertRaises(ValueError):
            self.monitor.ingest(self.event("old", 1, 151, self.now - 4000), self.now)


if __name__ == "__main__":
    unittest.main()
