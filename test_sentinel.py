import unittest

from sentinel import (
    DigitalTwin,
    Direction,
    MovementEvent,
    Person,
    Quality,
    SensorReading,
    SensorService,
    SensorSpec,
    ZonePolicy,
)


class OffshoreDigitalTwinTests(unittest.TestCase):
    def setUp(self):
        self.people = {
            "p1": Person("p1", "technician"),
            "p2": Person("p2", "supervisor"),
            "p3": Person("p3", "technician"),
        }
        self.twin = DigitalTwin(
            "vessel-1",
            {
                "engine-room": ZonePolicy("engine-room", 2, frozenset({"technician", "supervisor"}), True),
                "bridge": ZonePolicy("bridge", 1, frozenset({"supervisor"})),
            },
            2,
            self.people,
        )

    def movement(self, event_id, person_id, direction, zone_id, timestamp=1000):
        return MovementEvent(event_id, person_id, direction, zone_id, timestamp)

    def test_pob_and_zone_occupancy_follow_badge_events(self):
        self.twin.apply_movement(self.movement("m1", "p1", Direction.EMBARK, "engine-room"))
        self.twin.apply_movement(self.movement("m2", "p2", Direction.EMBARK, "bridge"))
        self.assertEqual(self.twin.people_on_board, 2)
        self.assertEqual(self.twin.assess_zone("engine-room")["people"], 1)
        self.twin.apply_movement(self.movement("m3", "p1", Direction.DISEMBARK, "engine-room"))
        self.assertEqual(self.twin.people_on_board, 1)

    def test_zone_role_and_pob_limits_are_enforced(self):
        self.people["p3"] = Person("p3", "visitor")
        with self.assertRaises(PermissionError):
            self.twin.apply_movement(self.movement("m1", "p3", Direction.EMBARK, "bridge"))
        self.people["p3"] = Person("p3", "technician")
        self.twin.apply_movement(self.movement("m2", "p1", Direction.EMBARK, "engine-room"))
        self.twin.apply_movement(self.movement("m3", "p2", Direction.EMBARK, "bridge"))
        with self.assertRaises(OverflowError):
            self.twin.apply_movement(self.movement("m4", "p3", Direction.EMBARK, "engine-room"))

    def test_movement_replay_is_rejected(self):
        event = self.movement("m1", "p1", Direction.EMBARK, "engine-room")
        self.twin.apply_movement(event)
        with self.assertRaises(ValueError):
            self.twin.apply_movement(event)

    def test_pob_reconciliation_emits_alert(self):
        self.assertFalse(self.twin.reconcile_badge_totals(4, now=1000))
        self.assertEqual(self.twin.alerts[0].severity, "critical")

    def test_sensor_calibration_and_quality_checks(self):
        service = SensorService([SensorSpec("press-1", "pressure", 0, 4095, 0, 250, "bar", 60)])
        measurement = service.ingest(SensorReading("press-1", 1, 2048, 1000, Quality.GOOD), now=1000)
        self.assertAlmostEqual(measurement.value, 125.0305, places=3)
        with self.assertRaises(ValueError):
            service.ingest(SensorReading("press-1", 2, 2048, 1000, Quality.BAD), now=1000)

    def test_stale_or_replayed_sensor_sequence_is_rejected(self):
        service = SensorService([SensorSpec("press-1", "pressure", 0, 100, 0, 200, "bar", 10)])
        service.ingest(SensorReading("press-1", 4, 50, 1000, Quality.GOOD), now=1000)
        with self.assertRaises(ValueError):
            service.ingest(SensorReading("press-1", 3, 50, 1000, Quality.GOOD), now=1000)
        with self.assertRaises(ValueError):
            service.ingest(SensorReading("press-1", 5, 50, 900, Quality.GOOD), now=1000)


if __name__ == "__main__":
    unittest.main()
