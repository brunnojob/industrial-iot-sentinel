from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
        if self.raw_min >= self.raw_max or self.eu_min >= self.eu_max or self.max_age_seconds < 1:
            raise ValueError("invalid sensor specification")


@dataclass(frozen=True)
class SensorReading:
    sensor_id: str
    sequence: int
    value: float
    timestamp: float
    quality: Quality


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
        if not self.zone_id or self.capacity < 1:
            raise ValueError("invalid zone policy")


@dataclass(frozen=True)
class Person:
    person_id: str
    role: str
    active: bool = True


@dataclass(frozen=True)
class MovementEvent:
    event_id: str
    person_id: str
    direction: Direction
    zone_id: str | None  # Permitido None para desembarque total da embarcação
    timestamp: float


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

    def __post_init__(self) -> None:
        if not self.vessel_id or self.max_persons_on_board < 1:
            raise ValueError("invalid vessel limits")
        self.occupants = {zone_id: set() for zone_id in self.zones}

    def apply_movement(self, event: MovementEvent) -> dict[str, Any]:
        if not event.event_id or event.event_id in self.movement_ids:
            raise ValueError("duplicate or empty movement event")
        
        person = self.people.get(event.person_id)
        if person is None or not person.active:
            raise PermissionError("person is not authorized or inactive")

        # Caso seja desembarque total da embarcação (zone_id = None)
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
            return self._build_response(found_zone)

        # Validação normal de zona
        policy = self.zones.get(event.zone_id)  # type: ignore
        if policy is None:
            raise KeyError("zone does not exist")

        if person.role not in policy.permitted_roles:
            raise PermissionError("role is not permitted in zone")

        zone_people = self.occupants[event.zone_id]  # type: ignore

        if event.direction is Direction.EMBARK:
            # Melhoria real: se a pessoa já estiver noutra zona, removemos de lá primeiro (transição fluida)
            for z_id, occupants_set in self.occupants.items():
                if event.person_id in occupants_set:
                    occupants_set.remove(event.person_id)

            board_count = self.people_on_board
            if board_count >= self.max_persons_on_board:
                self._alert("critical", event.zone_id, "vessel_pob_limit_exceeded", event.timestamp)  # type: ignore
                raise OverflowError("vessel POB limit reached")
            
            if len(zone_people) >= policy.capacity:
                self._alert("high", event.zone_id, "zone_capacity_exceeded", event.timestamp)  # type: ignore
                raise OverflowError("zone capacity reached")
            
            zone_people.add(event.person_id)
        else:
            if event.person_id not in zone_people:
                raise ValueError("person is not recorded in zone")
            zone_people.remove(event.person_id)

        self.movement_ids.add(event.event_id)
        return self._build_response(event.zone_id)  # type: ignore

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

    def reconcile_badge_totals(self, access_total: int, now: float | None = None) -> bool:
        if access_total < 0:
            raise ValueError("access total cannot be negative")
        if access_total != self.people_on_board:
            self._alert("critical", self.vessel_id, f"pob_mismatch:{access_total}:{self.people_on_board}", time.time() if now is None else now)
            return False
        return True

    def _alert(self, severity: str, subject: str, reason: str, timestamp: float) -> None:
        self.alerts.append(Alert(f"alt-{len(self.alerts) + 1}", severity, subject, reason, timestamp))


class SensorService:
    def __init__(self, specifications: list[SensorSpec]):
        self.specifications = {item.sensor_id: item for item in specifications}
        self.last_sequence: dict[str, int] = {}

    def ingest(self, reading: SensorReading, now: float | None = None) -> Measurement:
        current = time.time() if now is None else now
        specification = self.specifications.get(reading.sensor_id)
        if specification is None:
            raise KeyError("unregistered sensor")
        if reading.quality is not Quality.GOOD:
            raise ValueError("sensor quality is not good")
        if not specification.raw_min <= reading.value <= specification.raw_max:
            raise ValueError("raw sensor value is outside calibrated range")
        if reading.timestamp < current - specification.max_age_seconds or reading.timestamp > current + 5:
            raise ValueError("sensor reading is stale or from the future")
        if reading.sequence <= self.last_sequence.get(reading.sensor_id, -1):
            raise ValueError("sensor sequence is not monotonic")
        self.last_sequence[reading.sensor_id] = reading.sequence
        fraction = (reading.value - specification.raw_min) / (specification.raw_max - specification.raw_min)
        engineering_value = specification.eu_min + fraction * (specification.eu_max - specification.eu_min)
        return Measurement(
            reading.sensor_id,
            specification.metric,
            round(engineering_value, 4),
            specification.unit,
            reading.timestamp,
            reading.quality,
        )


def sample_snapshot() -> dict[str, Any]:
    people = {
        "crew-100": Person("crew-100", "technician"),
        "crew-101": Person("crew-101", "supervisor"),
        "crew-102": Person("crew-102", "technician"),
    }
    twin = DigitalTwin(
        "rf-offshore-demo",
        {
            "engine-room": ZonePolicy("engine-room", 2, frozenset({"technician", "supervisor"}), True),
            "control-room": ZonePolicy("control-room", 4, frozenset({"supervisor"})),
        },
        20,
        people,
    )
    twin.apply_movement(MovementEvent("gate-1", "crew-100", Direction.EMBARK, "engine-room", 1))
    twin.apply_movement(MovementEvent("gate-2", "crew-101", Direction.EMBARK, "control-room", 2))
    return {
        "vessel_id": twin.vessel_id,
        "people_on_board": twin.people_on_board,
        "zones": [twin.assess_zone(zone_id) for zone_id in twin.zones],
        "alerts": [alert.__dict__ for alert in twin.alerts],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(sample_snapshot(), indent=2))
