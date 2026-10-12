import tempfile
import threading
import unittest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from events import DurableTwin


class SharedJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "twin.db"
        self.config = {
            "vesselId": "shared-vessel",
            "capacity": 2,
            "zones": [
                {"id": "a", "capacity": 1, "roles": ["crew"]},
                {"id": "b", "capacity": 1, "roles": ["crew"]},
            ],
            "people": [{"id": "one", "role": "crew"}, {"id": "two", "role": "crew"}],
        }

    def open_twin(self):
        twin = DurableTwin(self.path, self.config)
        self.addCleanup(twin.db.close)
        return twin

    def movement(self, event_id, person="one", zone="a"):
        return {
            "eventId": event_id,
            "personId": person,
            "direction": "embark",
            "zoneId": zone,
            "timestamp": 1000,
        }

    def test_capacity_is_checked_against_other_connections_commits(self):
        first, second = self.open_twin(), self.open_twin()
        first.submit(self.movement("1"))
        with self.assertRaises(OverflowError):
            second.submit(self.movement("2", person="two"))
        self.assertEqual(second.snapshot()["events"], 1)
        recovered = self.open_twin()
        self.assertEqual(recovered.snapshot()["peopleOnBoard"], 1)

    def test_vessel_capacity_is_shared_across_connections(self):
        self.config["capacity"] = 1
        first, second = self.open_twin(), self.open_twin()
        first.submit(self.movement("1"))
        with self.assertRaises(OverflowError):
            second.submit(self.movement("2", person="two", zone="b"))
        self.assertEqual(second.snapshot()["peopleOnBoard"], 1)

    def test_snapshots_and_duplicates_refresh_occupancy(self):
        first, second = self.open_twin(), self.open_twin()
        event = self.movement("1")
        first.submit(event)
        self.assertEqual(second.submit(event), {"duplicate": True, **first.snapshot()})
        self.assertEqual(second.snapshot(), first.snapshot())
        second.submit(self.movement("2", person="two", zone="b"))
        self.assertEqual(first.snapshot(), second.snapshot())
        self.assertEqual(first.snapshot()["peopleOnBoard"], 2)

    def test_cross_connection_departure_and_transfer_replay(self):
        first, second = self.open_twin(), self.open_twin()
        first.submit(self.movement("1"))
        second.submit(self.movement("2", zone="b"))
        first.submit({
            **self.movement("3"), "direction": "disembark", "zoneId": None
        })
        second.submit(self.movement("4", person="two", zone="b"))
        recovered = self.open_twin()
        self.assertEqual(first.snapshot(), recovered.snapshot())
        self.assertEqual(second.snapshot(), recovered.snapshot())
        self.assertEqual(recovered.twin.occupants, {"a": set(), "b": {"two"}})
        self.assertEqual(recovered.snapshot()["events"], 4)

    def test_simultaneous_capacity_contenders_commit_only_one_event(self):
        twins = [self.open_twin(), self.open_twin()]
        barrier = threading.Barrier(2)

        def submit(index):
            barrier.wait(timeout=5)
            try:
                twins[index].submit(self.movement(str(index), person=("one", "two")[index]))
                return "accepted"
            except OverflowError:
                return "full"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertCountEqual(results, ["accepted", "full"])
        recovered = self.open_twin()
        self.assertEqual(recovered.snapshot()["events"], 1)
        self.assertEqual(recovered.snapshot()["peopleOnBoard"], 1)

    def test_conflict_does_not_prevent_refresh_or_the_next_valid_event(self):
        first, second = self.open_twin(), self.open_twin()
        first.submit(self.movement("1"))
        with self.assertRaisesRegex(ValueError, "idempotency conflict"):
            second.submit(self.movement("1", zone="b"))
        second.submit(self.movement("2", person="two", zone="b"))
        self.assertEqual(first.snapshot(), second.snapshot())

    def test_snapshot_uses_one_database_version_during_a_concurrent_commit(self):
        first, second = self.open_twin(), self.open_twin()
        initial = first.snapshot()
        original_snapshot = first._snapshot

        def commit_during_snapshot():
            second.submit(self.movement("1"))
            return original_snapshot()

        with patch.object(first, "_snapshot", side_effect=commit_during_snapshot):
            self.assertEqual(first.snapshot(), initial)
        self.assertEqual(first.snapshot(), second.snapshot())
        self.assertEqual(first.snapshot()["events"], 1)

    def test_failed_commit_preserves_state_and_can_be_retried(self):
        twin = self.open_twin()
        original_db = twin.db
        failing_db = MagicMock(wraps=original_db)
        failing_db.commit.side_effect = sqlite3.OperationalError("disk full")
        with patch.object(twin, "db", failing_db):
            with self.assertRaisesRegex(sqlite3.OperationalError, "disk full"):
                twin.submit(self.movement("1"))
        self.assertEqual(twin.snapshot()["events"], 0)
        self.assertEqual(twin.snapshot()["peopleOnBoard"], 0)
        twin.submit(self.movement("1"))
        self.assertEqual(self.open_twin().snapshot()["peopleOnBoard"], 1)


if __name__ == "__main__":
    unittest.main()
