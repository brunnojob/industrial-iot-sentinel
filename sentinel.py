from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ThresholdRule:
    metric: str
    high: float
    clear_below: float
    consecutive: int = 2
    unit: str = ""

    def __post_init__(self) -> None:
        if not self.metric or self.clear_below >= self.high or self.consecutive < 1:
            raise ValueError("invalid threshold rule")


@dataclass
class Alert:
    sensor_id: str
    metric: str
    opened_at: float
    last_value: float
    occurrences: int = 1
    acknowledged: bool = False
    resolved_at: float | None = None

    @property
    def active(self) -> bool:
        return self.resolved_at is None


class TelemetrySentinel:
    def __init__(self, rules: list[ThresholdRule], max_age_seconds: int = 3600, future_skew_seconds: int = 30):
        self.rules = {rule.metric: rule for rule in rules}
        self.max_age_seconds = max_age_seconds
        self.future_skew_seconds = future_skew_seconds
        self.alerts: list[Alert] = []
        self._event_ids: set[str] = set()
        self._sequences: dict[str, int] = {}
        self._breach_counts: dict[tuple[str, str], int] = {}
        self._active: dict[tuple[str, str], Alert] = {}

    def ingest(self, event: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        event_id = str(event.get("event_id", ""))
        sensor_id = str(event.get("sensor_id", ""))
        metric = str(event.get("metric", ""))
        value = event.get("value")
        sequence = event.get("sequence")
        timestamp = event.get("timestamp")
        if not event_id or not sensor_id or metric not in self.rules:
            raise ValueError("event identity or metric is invalid")
        if event_id in self._event_ids:
            return {"accepted": False, "reason": "duplicate_event"}
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isinstance(timestamp, (int, float)) or not isinstance(sequence, int):
            raise ValueError("event fields have invalid types")
        if timestamp < current - self.max_age_seconds or timestamp > current + self.future_skew_seconds:
            raise ValueError("event timestamp is outside the accepted window")
        prior_sequence = self._sequences.get(sensor_id, -1)
        if sequence <= prior_sequence:
            raise ValueError("sensor sequence must increase monotonically")
        self._event_ids.add(event_id)
        self._sequences[sensor_id] = sequence
        key = (sensor_id, metric)
        rule = self.rules[metric]
        alert = self._active.get(key)
        if value >= rule.high:
            self._breach_counts[key] = self._breach_counts.get(key, 0) + 1
            if alert is None and self._breach_counts[key] >= rule.consecutive:
                alert = Alert(sensor_id, metric, float(timestamp), float(value))
                self._active[key] = alert
                self.alerts.append(alert)
            elif alert is not None:
                alert.last_value = float(value)
                alert.occurrences += 1
        else:
            self._breach_counts[key] = 0
            if alert is not None and value <= rule.clear_below:
                alert.last_value = float(value)
                alert.resolved_at = float(timestamp)
                del self._active[key]
        return {
            "accepted": True,
            "alert_active": key in self._active,
            "breach_count": self._breach_counts.get(key, 0),
        }

    def acknowledge(self, sensor_id: str, metric: str) -> None:
        alert = self._active.get((sensor_id, metric))
        if alert is None:
            raise KeyError("active alert not found")
        alert.acknowledged = True

    def snapshot(self) -> dict[str, Any]:
        return {
            "active_alerts": [
                {
                    "sensor_id": alert.sensor_id,
                    "metric": alert.metric,
                    "last_value": alert.last_value,
                    "occurrences": alert.occurrences,
                    "acknowledged": alert.acknowledged,
                    "opened_at": alert.opened_at,
                }
                for alert in self._active.values()
            ],
            "total_alerts": len(self.alerts),
            "accepted_event_ids": len(self._event_ids),
        }


def sample() -> list[dict[str, Any]]:
    now = time.time()
    sentinel = TelemetrySentinel([ThresholdRule("vibration_mm_s", 9.0, 6.0, consecutive=2, unit="mm/s")])
    events = [
        {"event_id": "evt-100", "sensor_id": "pump-3", "metric": "vibration_mm_s", "value": 9.4, "sequence": 1, "timestamp": now},
        {"event_id": "evt-101", "sensor_id": "pump-3", "metric": "vibration_mm_s", "value": 10.1, "sequence": 2, "timestamp": now + 1},
    ]
    return [sentinel.ingest(event, now=now + 1) for event in events]


if __name__ == "__main__":
    print(json.dumps({"results": sample()}, indent=2))
