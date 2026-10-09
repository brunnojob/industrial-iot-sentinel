import tempfile
import unittest
from pathlib import Path
from events import DurableTwin


class DurableTests(unittest.TestCase):
    def test_replay_and_rejected_transition_are_atomic(self):
        config = {
            "vesselId": "v",
            "capacity": 2,
            "zones": [
                {"id": "a", "capacity": 1, "roles": ["crew"]},
                {"id": "b", "capacity": 1, "roles": ["crew"]},
            ],
            "people": [{"id": "one", "role": "crew"}, {"id": "two", "role": "crew"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "twin.db"
            twin = DurableTwin(path, config)
            first = {
                "eventId": "1",
                "personId": "one",
                "direction": "embark",
                "zoneId": "a",
                "timestamp": 1000,
            }
            twin.submit(first)
            twin.submit({**first, "eventId": "2", "personId": "two", "zoneId": "b"})
            with self.assertRaises(OverflowError):
                twin.submit({**first, "eventId": "3", "zoneId": "b"})
            self.assertEqual(twin.twin.occupants["a"], {"one"})
            self.assertEqual(twin.snapshot()["events"], 2)
            twin.db.close()
            recovered = DurableTwin(path, config)
            self.assertEqual(recovered.snapshot()["peopleOnBoard"], 2)
            self.assertTrue(recovered.submit(first)["duplicate"])
            recovered.db.close()
