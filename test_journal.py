import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from events import DurableTwin


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "twin.db"
        self.config = {
            "vesselId": "v", "capacity": 2,
            "zones": [{"id": "deck", "capacity": 2, "roles": ["crew"]}],
            "people": [{"id": "one", "role": "crew"}, {"id": "two", "role": "crew"}],
        }

    def engine(self):
        engine = DurableTwin(self.path, self.config)
        self.addCleanup(engine.close)
        return engine

    def event(self, identifier, person="one", direction="embark", timestamp=1000):
        return {"eventId": identifier, "personId": person, "direction": direction, "zoneId": "deck", "timestamp": timestamp}

    def test_two_connections_refresh_before_capacity_checks(self):
        first, second = self.engine(), self.engine()
        first.submit(self.event("a"))
        second.submit(self.event("b", person="two"))
        self.assertEqual(second.snapshot()["peopleOnBoard"], 2)
        self.assertEqual(first.snapshot()["peopleOnBoard"], 2)
        second.submit(self.event("c", person="two", direction="disembark"))
        self.assertEqual(first.snapshot()["peopleOnBoard"], 1)

    def test_concurrent_duplicate_is_committed_once(self):
        first, second = self.engine(), self.engine()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(engine.submit, self.event("shared")) for engine in (first, second)]
            results = [future.result() for future in futures]
        self.assertEqual(sum(bool(result.get("duplicate")) for result in results), 1)
        self.assertEqual(first.snapshot()["events"], 1)
        self.assertEqual(second.snapshot()["peopleOnBoard"], 1)

    def test_batch_failure_rolls_back_all_new_movements(self):
        engine = self.engine()
        with self.assertRaises(ValueError):
            engine.submit_many([self.event("a"), self.event("b")])
        self.assertEqual(engine.snapshot()["events"], 0)
        self.assertEqual(engine.snapshot()["peopleOnBoard"], 0)
        engine.submit_many([self.event("a"), self.event("b", person="two")])
        self.assertEqual(engine.snapshot()["events"], 2)
        replay = engine.submit_many([self.event("a"), self.event("b", person="two")])
        self.assertTrue(all(result["duplicate"] for result in replay))

    def test_journal_insert_failure_preserves_memory_and_database(self):
        engine = self.engine()
        engine.db.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON movements BEGIN SELECT RAISE(ABORT,'write rejected'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            engine.submit(self.event("a"))
        self.assertEqual(engine.snapshot()["peopleOnBoard"], 0)
        self.assertEqual(engine.snapshot()["events"], 0)

    def test_duplicate_payload_is_semantic_but_conflicts_are_rejected(self):
        engine = self.engine()
        engine.submit(self.event("a"))
        self.assertTrue(engine.submit({**self.event("a"), "timestamp": 1000.0})["duplicate"])
        with self.assertRaises(ValueError):
            engine.submit({**self.event("a"), "personId": "two"})
        with self.assertRaises(ValueError):
            engine.submit({**self.event("a"), "ignored": "value"})

    def test_configuration_change_and_duplicate_ids_are_rejected(self):
        with self.engine():
            pass
        changed = {**self.config, "capacity": 3}
        with self.assertRaises(ValueError):
            DurableTwin(self.path, changed)
        duplicate = {**self.config, "people": self.config["people"] * 2}
        with self.assertRaises(ValueError):
            DurableTwin(self.path, duplicate)
        with self.assertRaises(ValueError):
            self.engine().submit_many([])


if __name__ == "__main__":
    unittest.main()
