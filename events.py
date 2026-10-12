from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from sentinel import DigitalTwin, Direction, MovementEvent, Person, ZonePolicy


class DurableTwin:
    def __init__(self, path, configuration):
        self.lock = threading.RLock()
        fingerprint = hashlib.sha256(
            json.dumps(configuration, sort_keys=True).encode()
        ).hexdigest()
        self.twin = DigitalTwin(
            configuration["vesselId"],
            {
                z["id"]: ZonePolicy(
                    z["id"],
                    z["capacity"],
                    frozenset(z["roles"]),
                    z.get("hazardous", False),
                )
                for z in configuration["zones"]
            },
            configuration["capacity"],
            {p["id"]: Person(p["id"], p["role"]) for p in configuration["people"]},
        )
        self.last_sequence = 0
        self.db = sqlite3.connect(path, timeout=15, check_same_thread=False)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(
                "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS movements(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,payload TEXT NOT NULL);"
            )
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute(
                "SELECT value FROM settings WHERE key='configuration'"
            ).fetchone()
            if prior and prior[0] != fingerprint:
                raise ValueError(
                    "stored event log requires its original vessel configuration"
                )
            self.db.execute(
                "INSERT OR IGNORE INTO settings VALUES ('configuration',?)",
                (fingerprint,),
            )
            self._refresh()
            self.db.commit()
        except Exception:
            self.db.close()
            raise

    def _refresh(self):
        rows = self.db.execute(
            "SELECT sequence,payload FROM movements WHERE sequence>? ORDER BY sequence",
            (self.last_sequence,),
        ).fetchall()
        if rows:
            candidate = copy.deepcopy(self.twin)
            for sequence, payload in rows:
                candidate.apply_movement(self.event(json.loads(payload)))
            self.twin = candidate
            self.last_sequence = rows[-1][0]

    @staticmethod
    def event(body):
        if not isinstance(body, dict) or not isinstance(
            body.get("timestamp"), (float, int)
        ):
            raise ValueError("normalized movement object required")
        return MovementEvent(
            body["eventId"],
            body["personId"],
            Direction(body["direction"]),
            body.get("zoneId"),
            body["timestamp"],
        )

    def submit(self, body):
        payload = json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if len(payload.encode()) > 8192:
            raise ValueError("movement too large")
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._refresh()
                event = self.event(body)
                prior = self.db.execute(
                    "SELECT payload FROM movements WHERE event_id=?", (event.event_id,)
                ).fetchone()
                if prior:
                    if prior[0] != payload:
                        raise ValueError("idempotency conflict")
                    result = {"duplicate": True, **self._snapshot()}
                    self.db.rollback()
                    return result
                candidate = copy.deepcopy(self.twin)
                result = candidate.apply_movement(event)
                cursor = self.db.execute(
                    "INSERT INTO movements(event_id,payload) VALUES (?,?)",
                    (event.event_id, payload),
                )
                self.db.commit()
                self.twin = candidate
                self.last_sequence = cursor.lastrowid
                return result
            except Exception:
                self.db.rollback()
                raise

    def snapshot(self):
        with self.lock:
            self.db.execute("BEGIN")
            try:
                self._refresh()
                return self._snapshot()
            finally:
                self.db.rollback()

    def _snapshot(self):
        return {
            "vesselId": self.twin.vessel_id,
            "peopleOnBoard": self.twin.people_on_board,
            "zones": [self.twin.assess_zone(zone) for zone in self.twin.zones],
            "events": self.db.execute("SELECT COUNT(*) FROM movements").fetchone()[0],
        }


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("configuration")
    parser.add_argument("--database", default=".local/twin.db")
    args = parser.parse_args()
    path = Path(args.database)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = DurableTwin(path, json.loads(Path(args.configuration).read_text()))
    try:
        for line in sys.stdin:
            if line.strip():
                engine.submit(json.loads(line))
        print(json.dumps(engine.snapshot(), sort_keys=True))
    finally:
        engine.db.close()
