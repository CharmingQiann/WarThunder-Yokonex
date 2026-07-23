from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TelemetrySnapshot:
    connected: bool = False
    active: bool = False
    vehicle_type: str = ""
    vehicle_name: str = ""
    gforce: float = 0.0
    speed_kmh: float = 0.0
    repairing: bool = False
    repair_time_s: float = 0.0
    raw_state: dict[str, Any] = field(default_factory=dict)
    raw_indicators: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HudRecord:
    record_id: int
    message: str


@dataclass(frozen=True)
class DetectedEvent:
    event_key: str
    data: dict[str, Any] = field(default_factory=dict)
    match_value: str | None = None


@dataclass(frozen=True)
class ContinuousOutput:
    ratio: float = 0.0
    event_key: str = ""
    command_id: str = ""
