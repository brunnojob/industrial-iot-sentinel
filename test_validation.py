import math
import unittest
from concurrent.futures import ThreadPoolExecutor

from sentinel import DigitalTwin, Direction, MovementEvent, Person, Quality, SensorReading, SensorService, SensorSpec, ZonePolicy


class ValidationTests(unittest.TestCase):
    def service(self):
        return SensorService([SensorSpec("s", "temperature", 0, 100, -50, 50, "C")])

    def test_extreme_finite_calibration_does_not_overflow(self):
        service = SensorService([SensorSpec("s", "v", -1e308, 1e308, -1e308, 1e308, "V")])
        for sequence, raw in enumerate((-1e308, 0, 1e308)):
            value = service.ingest(SensorReading("s", sequence, raw, 1000, Quality.GOOD), now=1000).value
            self.assertTrue(math.isfinite(value))
            self.assertEqual(value, raw)

    def test_timestamp_reversal_does_not_consume_sequence(self):
        service = self.service()
        service.ingest(SensorReading("s", 4, 50, 1000, Quality.GOOD), now=1000)
        with self.assertRaises(ValueError):
            service.ingest(SensorReading("s", 7, 50, 999, Quality.GOOD), now=1000)
        service.ingest(SensorReading("s", 7, 50, 1001, Quality.GOOD), now=1001)
        diagnostics = service.diagnostics()
        self.assertEqual(diagnostics["s"]["missing_sequences"], 2)
        diagnostics["s"]["last_sequence"] = 100
        self.assertEqual(service.diagnostics()["s"]["last_sequence"], 7)

    def test_concurrent_duplicate_has_one_success(self):
        service = self.service()
        reading = SensorReading("s", 1, 50, 1000, Quality.GOOD)
        def ingest(_):
            try:
                service.ingest(reading, now=1000)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(ingest, range(32))), 1)

    def test_wrong_scalar_types_and_nonfinite_timestamps_are_rejected(self):
        for capacity in (True, 1.5, "2"):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                ZonePolicy("z", capacity, frozenset({"crew"}))
        for timestamp in (True, math.nan, math.inf, -1):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                MovementEvent("e", "p", Direction.EMBARK, "z", timestamp)
        with self.assertRaises(ValueError):
            MovementEvent("e", "p", "embark", "z", 1000)
        with self.assertRaises(ValueError):
            SensorReading("s", True, 50, 1000, Quality.GOOD)

    def test_movement_order_and_configuration_identity(self):
        zones = {"z": ZonePolicy("z", 2, frozenset({"crew"}))}
        people = {"p": Person("p", "crew")}
        twin = DigitalTwin("v", zones, 2, people)
        twin.apply_movement(MovementEvent("1", "p", Direction.EMBARK, "z", 1000))
        with self.assertRaises(ValueError):
            twin.apply_movement(MovementEvent("2", "p", Direction.DISEMBARK, None, 999))
        self.assertEqual(twin.people_on_board, 1)
        twin.apply_movement(MovementEvent("2", "p", Direction.DISEMBARK, None, 1001))
        with self.assertRaises(ValueError):
            DigitalTwin("v", {"wrong": zones["z"]}, 2, people)
        with self.assertRaises(ValueError):
            twin.reconcile_badge_totals(True, now=1000)


if __name__ == "__main__":
    unittest.main()
