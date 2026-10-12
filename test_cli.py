import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from events import DurableTwin


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(__file__).resolve().parent
        self.path = Path(self.directory.name) / "journal.db"
        self.config_path = self.root / "examples/vessel.json"

    def run_cli(self, data, *options):
        return subprocess.run(
            [sys.executable, str(self.root / "events.py"), str(self.config_path), "--database", str(self.path), *options],
            input=data, capture_output=True, text=True, timeout=10,
        )

    def snapshot(self):
        with DurableTwin(self.path, json.loads(self.config_path.read_text())) as engine:
            return engine.snapshot()

    def test_documented_input_and_replay_work_end_to_end(self):
        data = (self.root / "examples/movements.jsonl").read_text()
        first = self.run_cli(data, "--atomic-batch")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["events"], 3)
        self.assertEqual(json.loads(first.stdout)["peopleOnBoard"], 1)
        replay = self.run_cli(data, "--atomic-batch", "--ack-jsonl")
        self.assertEqual(replay.returncode, 0, replay.stderr)
        lines = [json.loads(line) for line in replay.stdout.splitlines()]
        self.assertTrue(all(line["result"]["duplicate"] for line in lines[:-1]))
        self.assertEqual(lines[-1]["type"], "snapshot")

    def test_invalid_line_does_not_partially_commit_atomic_batch(self):
        first = (self.root / "examples/movements.jsonl").read_text().splitlines()[0]
        result = self.run_cli(first + "\ninvalid\n", "--atomic-batch", "--ack-jsonl")
        self.assertEqual(result.returncode, 2)
        self.assertIn("line 2", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.snapshot()["events"], 0)

    def test_streaming_reports_committed_prefix_on_failure(self):
        first = (self.root / "examples/movements.jsonl").read_text().splitlines()[0]
        result = self.run_cli(first + "\ninvalid\n", "--ack-jsonl")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["type"], "movement")
        self.assertEqual(self.snapshot()["events"], 1)

    def test_duplicate_json_keys_and_large_lines_are_rejected(self):
        data = '{"eventId":"a","eventId":"b","personId":"crew-1","direction":"embark","zoneId":"deck","timestamp":1000}\n'
        result = self.run_cli(data)
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate JSON field", result.stderr)
        result = self.run_cli("x" * 9000 + "\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("8192", result.stderr)

    def test_oversized_integer_returns_validation_error(self):
        data = json.dumps({"eventId": "a", "personId": "crew-1", "direction": "embark", "zoneId": "deck", "timestamp": 10 ** 400})
        result = self.run_cli(data)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
