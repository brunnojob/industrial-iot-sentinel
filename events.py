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
        self.closed = False
        self.last_sequence = 0
        self.twin = self.build_twin(configuration)
        fingerprint = hashlib.sha256(
            json.dumps(configuration, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
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
                raise ValueError("stored event log requires its original vessel configuration")
            self.db.execute(
                "INSERT OR IGNORE INTO settings VALUES ('configuration',?)", (fingerprint,)
            )
            self._refresh()
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            self.closed = True
            raise

    @staticmethod
    def build_twin(configuration):
        if not isinstance(configuration, dict):
            raise ValueError("configuration object required")
        zones = configuration["zones"]
        people = configuration["people"]
        if not isinstance(zones, list) or not isinstance(people, list):
            raise ValueError("zones and people must be arrays")
        policies = [ZonePolicy(z["id"], z["capacity"], frozenset(z["roles"]), z.get("hazardous", False)) for z in zones]
        personnel = [Person(p["id"], p["role"], p.get("active", True)) for p in people]
        if len({z.zone_id for z in policies}) != len(policies):
            raise ValueError("duplicate zone identifier")
        if len({p.person_id for p in personnel}) != len(personnel):
            raise ValueError("duplicate person identifier")
        return DigitalTwin(
            configuration["vesselId"],
            {z.zone_id: z for z in policies},
            configuration["capacity"],
            {p.person_id: p for p in personnel},
        )

    @staticmethod
    def event(body):
        required = {"eventId", "personId", "direction", "timestamp"}
        if not isinstance(body, dict) or not required <= body.keys() or body.keys() - required - {"zoneId"}:
            raise ValueError("normalized movement object required")
        return MovementEvent(
            body["eventId"], body["personId"], Direction(body["direction"]),
            body.get("zoneId"), body["timestamp"],
        )

    def _refresh(self):
        rows = self.db.execute(
            "SELECT sequence,payload FROM movements WHERE sequence>? ORDER BY sequence", (self.last_sequence,)
        ).fetchall()
        if not rows:
            return
        candidate = copy.deepcopy(self.twin)
        for sequence, payload in rows:
            candidate.apply_movement(self.event(json.loads(payload)))
        self.twin = candidate
        self.last_sequence = rows[-1][0]

    @staticmethod
    def state(twin, count):
        return {
            "vesselId": twin.vessel_id,
            "peopleOnBoard": twin.people_on_board,
            "zones": [twin.assess_zone(zone) for zone in twin.zones],
            "events": count,
        }

    def submit(self, body):
        return self.submit_many([body])[0]

    def submit_many(self, bodies):
        if not isinstance(bodies, (list, tuple)) or not 1 <= len(bodies) <= 1000:
            raise ValueError("batch must contain 1 to 1000 movements")
        prepared = []
        for body in bodies:
            event = self.event(body)
            payload = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(payload.encode()) > 8192:
                raise ValueError("movement too large")
            prepared.append((event, payload))
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._refresh()
                candidate = copy.deepcopy(self.twin)
                count = self.db.execute("SELECT COUNT(*) FROM movements").fetchone()[0]
                sequence = self.last_sequence
                results = []
                for event, payload in prepared:
                    prior = self.db.execute(
                        "SELECT payload FROM movements WHERE event_id=?", (event.event_id,)
                    ).fetchone()
                    if prior:
                        if self.event(json.loads(prior[0])) != event:
                            raise ValueError("idempotency conflict")
                        results.append({"duplicate": True, **self.state(candidate, count)})
                        continue
                    result = candidate.apply_movement(event)
                    cursor = self.db.execute(
                        "INSERT INTO movements(event_id,payload) VALUES (?,?)", (event.event_id, payload)
                    )
                    sequence = cursor.lastrowid
                    count += 1
                    results.append(result)
                self.db.commit()
                self.twin = candidate
                self.last_sequence = sequence
                return results
            except Exception:
                self.db.rollback()
                raise

    def snapshot(self):
        with self.lock:
            self.db.execute("BEGIN")
            try:
                self._refresh()
                result = self._snapshot()
                self.db.commit()
                return result
            except Exception:
                self.db.rollback()
                raise

    def _snapshot(self):
        count = self.db.execute("SELECT COUNT(*) FROM movements").fetchone()[0]
        return self.state(self.twin, count)

    def close(self):
        with self.lock:
            if not self.closed:
                self.db.close()
                self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("configuration")
    parser.add_argument("--database", default=".local/twin.db")
    args = parser.parse_args()
    path = Path(args.database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DurableTwin(path, json.loads(Path(args.configuration).read_text())) as engine:
        for line in sys.stdin:
            if line.strip():
                engine.submit(json.loads(line))
        print(json.dumps(engine.snapshot(), sort_keys=True))
