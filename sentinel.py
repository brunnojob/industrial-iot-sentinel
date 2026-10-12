from __future__ import annotations

import time
import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _positive_integer(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


class Quality(str, Enum):
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"


class Direction(str, Enum):
    EMBARK = "embark"
    DISEMBARK = "disembark"


@dataclass(frozen=True)
class SensorSpec:
    sensor_id: str
    metric: str
    raw_min: float
    raw_max: float
    eu_min: float
    eu_max: float
    unit: str
    max_age_seconds: int = 60

    def __post_init__(self) -> None:
        if (
            not all(_finite(value) for value in (self.raw_min, self.raw_max, self.eu_min, self.eu_max))
            or not _identifier(self.sensor_id)
            or not _identifier(self.metric)
            or not _identifier(self.unit)
            or self.raw_min >= self.raw_max
            or self.eu_min >= self.eu_max
            or not _positive_integer(self.max_age_seconds)
        ):
            raise ValueError("invalid sensor specification")


@dataclass(frozen=True)
class SensorReading:
    sensor_id: str
    sequence: int
    value: float
    timestamp: float
    quality: Quality

    def __post_init__(self) -> None:
        if (
            not _identifier(self.sensor_id)
            or isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
            or not _finite(self.value)
            or not _finite(self.timestamp)
            or not isinstance(self.quality, Quality)
        ):
            raise ValueError("invalid sensor reading")


@dataclass(frozen=True)
class Measurement:
    sensor_id: str
    metric: str
    value: float
    unit: str
    timestamp: float
    quality: Quality


@dataclass(frozen=True)
class ZonePolicy:
    zone_id: str
    capacity: int
    permitted_roles: frozenset[str]
    hazardous: bool = False

    def __post_init__(self) -> None:
        if (
            not _identifier(self.zone_id)
            or not _positive_integer(self.capacity)
            or not isinstance(self.permitted_roles, frozenset)
            or not self.permitted_roles
            or not all(_identifier(role) for role in self.permitted_roles)
            or not isinstance(self.hazardous, bool)
        ):
            raise ValueError("invalid zone policy")


@dataclass(frozen=True)
class Person:
    person_id: str
    role: str
    active: bool = True

    def __post_init__(self) -> None:
        if not _identifier(self.person_id) or not _identifier(self.role) or not isinstance(self.active, bool):
            raise ValueError("invalid person")


@dataclass(frozen=True)
class MovementEvent:
    event_id: str
    person_id: str
    direction: Direction
    zone_id: str | None
    timestamp: float

    def __post_init__(self) -> None:
        if (
            not _identifier(self.event_id)
            or not _identifier(self.person_id)
            or not isinstance(self.direction, Direction)
            or (self.zone_id is not None and not _identifier(self.zone_id))
            or (self.direction is Direction.EMBARK and self.zone_id is None)
            or not _finite(self.timestamp)
            or self.timestamp < 0
        ):
            raise ValueError("invalid movement event")


@dataclass(frozen=True)
class Alert:
    alert_id: str
    severity: str
    subject: str
    reason: str
    timestamp: float


@dataclass
class DigitalTwin:
    vessel_id: str
    zones: dict[str, ZonePolicy]
    max_persons_on_board: int
    people: dict[str, Person]
    occupants: dict[str, set[str]] = field(default_factory=dict)
    movement_ids: set[str] = field(default_factory=set)
    alerts: list[Alert] = field(default_factory=list)
    last_movement_timestamp: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _identifier(self.vessel_id) or not _positive_integer(self.max_persons_on_board):
            raise ValueError("invalid vessel limits")
        if any(key != policy.zone_id for key, policy in self.zones.items()):
            raise ValueError("zone identity mismatch")
        if any(key != person.person_id for key, person in self.people.items()):
            raise ValueError("person identity mismatch")
        if self.occupants or self.movement_ids or self.last_movement_timestamp:
            raise ValueError("initial occupancy must be recovered through movement events")
        self.occupants = {zone_id: set() for zone_id in self.zones}

    def apply_movement(self, event: MovementEvent) -> dict[str, Any]:
        if not event.event_id or event.event_id in self.movement_ids:
            raise ValueError("duplicate or empty movement event")

        person = self.people.get(event.person_id)
        if person is None or not person.active:
            raise PermissionError("person is not authorized or inactive")

        if event.timestamp < self.last_movement_timestamp.get(event.person_id, -1):
            raise ValueError("movement timestamp is not monotonic for person")

        if event.direction is Direction.DISEMBARK and event.zone_id is None:
            found_zone = None
            for z_id, occupants_set in self.occupants.items():
                if event.person_id in occupants_set:
                    found_zone = z_id
                    break
            if found_zone is None:
                raise ValueError("person is not on board")
            self.occupants[found_zone].remove(event.person_id)
            self.movement_ids.add(event.event_id)
            self.last_movement_timestamp[event.person_id] = event.timestamp
            return self._build_response(found_zone)

        policy = self.zones.get(event.zone_id)
        if policy is None:
            raise KeyError("zone does not exist")

        if person.role not in policy.permitted_roles:
            raise PermissionError("role is not permitted in zone")

        zone_people = self.occupants[event.zone_id]

        if event.direction is Direction.EMBARK:
            current_zone = next(
                (
                    z
                    for z, people in self.occupants.items()
                    if event.person_id in people
                ),
                None,
            )
            if current_zone == event.zone_id:
                raise ValueError("person already recorded in destination zone")
            if (
                current_zone is None
                and self.people_on_board >= self.max_persons_on_board
            ):
                self._alert(
                    "critical",
                    event.zone_id,
                    "vessel_pob_limit_exceeded",
                    event.timestamp,
                )
                raise OverflowError("vessel POB limit reached")
            if len(zone_people) >= policy.capacity:
                self._alert(
                    "high", event.zone_id, "zone_capacity_exceeded", event.timestamp
                )
                raise OverflowError("zone capacity reached")
            if current_zone is not None:
                self.occupants[current_zone].remove(event.person_id)
            zone_people.add(event.person_id)
        else:
            if event.person_id not in zone_people:
                raise ValueError("person is not recorded in zone")
            zone_people.remove(event.person_id)

        self.movement_ids.add(event.event_id)
        self.last_movement_timestamp[event.person_id] = event.timestamp
        return self._build_response(event.zone_id)

    def _build_response(self, zone_id: str) -> dict[str, Any]:
        zone_people = self.occupants[zone_id]
        return {
            "vessel_id": self.vessel_id,
            "zone_id": zone_id,
            "people_in_zone": len(zone_people),
            "people_on_board": self.people_on_board,
            "capacity_remaining": self.max_persons_on_board - self.people_on_board,
        }

    @property
    def people_on_board(self) -> int:
        return sum(len(person_ids) for person_ids in self.occupants.values())

    def assess_zone(self, zone_id: str) -> dict[str, Any]:
        policy = self.zones.get(zone_id)
        if policy is None:
            raise KeyError(zone_id)
        current = self.occupants[zone_id]
        ratio = len(current) / policy.capacity if policy.capacity > 0 else 0.0
        severity = "critical" if ratio >= 1 else "warning" if ratio >= 0.8 else "normal"
        return {
            "zone_id": zone_id,
            "people": len(current),
            "capacity": policy.capacity,
            "occupancy_ratio": round(ratio, 3),
            "severity": severity,
            "hazardous": policy.hazardous,
            "people_on_board": self.people_on_board,
        }

    def reconcile_badge_totals(
        self, access_total: int, now: float | None = None
    ) -> bool:
        if isinstance(access_total, bool) or not isinstance(access_total, int) or access_total < 0:
            raise ValueError("access total cannot be negative")
        timestamp = time.time() if now is None else now
        if not _finite(timestamp):
            raise ValueError("finite reconciliation timestamp required")
        if access_total != self.people_on_board:
            self._alert(
                "critical",
                self.vessel_id,
                f"pob_mismatch:{access_total}:{self.people_on_board}",
                timestamp,
            )
            return False
        return True

    def _alert(
        self, severity: str, subject: str, reason: str, timestamp: float
    ) -> None:
        self.alerts.append(
            Alert(f"alt-{len(self.alerts) + 1}", severity, subject, reason, timestamp)
        )


class SensorService:
    def __init__(self, specifications: list[SensorSpec]):
        self.specifications = {item.sensor_id: item for item in specifications}
        if len(self.specifications) != len(specifications):
            raise ValueError("duplicate sensor specification")
        self.last_sequence: dict[str, int] = {}
        self.last_timestamp: dict[str, float] = {}
        self.missing_sequences: dict[str, int] = {}
        self._lock = threading.RLock()

    def ingest(self, reading: SensorReading, now: float | None = None) -> Measurement:
        with self._lock:
            return self._ingest(reading, now)

    def _ingest(self, reading: SensorReading, now: float | None) -> Measurement:
        current = time.time() if now is None else now
        if not all(_finite(value) for value in (current, reading.value, reading.timestamp)):
            raise ValueError("finite reading and clock required")
        if isinstance(reading.sequence, bool) or not isinstance(reading.sequence, int) or reading.sequence < 0:
            raise ValueError("non-negative integer sequence required")
        specification = self.specifications.get(reading.sensor_id)
        if specification is None:
            raise KeyError("unregistered sensor")
        if reading.quality is not Quality.GOOD:
            raise ValueError("sensor quality is not good")
        if not specification.raw_min <= reading.value <= specification.raw_max:
            raise ValueError("raw sensor value is outside calibrated range")
        if (
            reading.timestamp < current - specification.max_age_seconds
            or reading.timestamp > current + 5
        ):
            raise ValueError("sensor reading is stale or from the future")
        if reading.sequence <= self.last_sequence.get(reading.sensor_id, -1):
            raise ValueError("sensor sequence is not monotonic")
        if reading.timestamp < self.last_timestamp.get(reading.sensor_id, -math.inf):
            raise ValueError("sensor timestamp is not monotonic")
        span = specification.raw_max - specification.raw_min
        if math.isfinite(span):
            fraction = (reading.value - specification.raw_min) / span
        else:
            scale = max(abs(specification.raw_min), abs(specification.raw_max))
            fraction = (reading.value / scale - specification.raw_min / scale) / (
                specification.raw_max / scale - specification.raw_min / scale
            )
        fraction = min(1.0, max(0.0, fraction))
        engineering_value = (1.0 - fraction) * specification.eu_min + fraction * specification.eu_max
        if not math.isfinite(engineering_value):
            raise ValueError("calibration produced a non-finite value")
        previous = self.last_sequence.get(reading.sensor_id)
        if previous is not None:
            self.missing_sequences[reading.sensor_id] = self.missing_sequences.get(reading.sensor_id, 0) + reading.sequence - previous - 1
        self.last_sequence[reading.sensor_id] = reading.sequence
        self.last_timestamp[reading.sensor_id] = reading.timestamp
        return Measurement(
            reading.sensor_id,
            specification.metric,
            round(engineering_value, 4),
            specification.unit,
            reading.timestamp,
            reading.quality,
        )

    def diagnostics(self) -> dict[str, dict[str, int | float]]:
        with self._lock:
            return {
                sensor_id: {
                    "last_sequence": sequence,
                    "last_timestamp": self.last_timestamp[sensor_id],
                    "missing_sequences": self.missing_sequences.get(sensor_id, 0),
                }
                for sensor_id, sequence in self.last_sequence.items()
            }


def sample_snapshot() -> dict[str, Any]:
    people = {
        "crew-100": Person("crew-100", "technician"),
        "crew-101": Person("crew-101", "supervisor"),
        "crew-102": Person("crew-102", "technician"),
    }
    twin = DigitalTwin(
        "rf-offshore-demo",
        {
            "engine-room": ZonePolicy(
                "engine-room", 2, frozenset({"technician", "supervisor"}), True
            ),
            "control-room": ZonePolicy("control-room", 4, frozenset({"supervisor"})),
        },
        20,
        people,
    )
    twin.apply_movement(
        MovementEvent("gate-1", "crew-100", Direction.EMBARK, "engine-room", 1)
    )
    twin.apply_movement(
        MovementEvent("gate-2", "crew-101", Direction.EMBARK, "control-room", 2)
    )
    return {
        "vessel_id": twin.vessel_id,
        "people_on_board": twin.people_on_board,
        "zones": [twin.assess_zone(zone_id) for zone_id in twin.zones],
        "alerts": [alert.__dict__ for alert in twin.alerts],
    }


if __name__ == "__main__":
    import json

    print(json.dumps(sample_snapshot(), indent=2))

