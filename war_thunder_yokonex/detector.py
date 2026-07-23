from __future__ import annotations

import re
import time
from collections.abc import Callable

from .config import Settings
from .models import ContinuousOutput, DetectedEvent, HudRecord, TelemetrySnapshot


ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]")
# 这些是插件的稳定业务规则，用户无需理解或反复调整。
GFORCE_MIN = 1.0
GFORCE_MAX = 10.0
GFORCE_THRESHOLDS = (3.0, 6.0, 9.0)
GFORCE_HYSTERESIS = 0.5
SPEED_MIN = 0.0
SPEED_MAX = 60.0
SPEED_THRESHOLDS = (10.0, 30.0, 50.0)
SPEED_HYSTERESIS = 3.0
MINIMUM_EVENT_INTERVAL_S = 0.8
KILL_VERBS = (
    "击落了", "击毁了", "摧毁了", "shot down", "destroyed", "set afire",
    "critically damaged", "збив", "уничтожил",
)
CRASH_VERBS = ("已坠毁", "has crashed", "crashed", "разбился")


class EventDetector:
    """把连续遥测转换成稳定事件，并计算 GameHub 连续输出强度。"""

    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self.clock = clock
        self.battle_active = False
        self.base_mode = ""
        self.in_cas = False
        self.repairing = False
        self.last_vehicle_type = ""
        self.g_band = 0
        self.speed_band = 0
        self._last_event_at: dict[str, float] = {}

    def process(
        self,
        snapshot: TelemetrySnapshot,
        hud_records: list[HudRecord] | None = None,
    ) -> tuple[list[DetectedEvent], ContinuousOutput]:
        events: list[DetectedEvent] = []
        hud_records = hud_records or []

        if snapshot.active and not self.battle_active:
            self.battle_active = True
            self.base_mode = snapshot.vehicle_type
            self.last_vehicle_type = snapshot.vehicle_type
            events.append(self._event("war_thunder.battle_start", snapshot))
        elif not snapshot.active and self.battle_active:
            events.append(self._event("war_thunder.battle_end", snapshot))
            self._reset_battle()
            return self._filter(events), ContinuousOutput()

        if not snapshot.active:
            return [], ContinuousOutput()

        events.extend(self._detect_cas(snapshot))
        events.extend(self._detect_repair(snapshot))
        events.extend(self._detect_bands(snapshot))
        events.extend(self._detect_hud(snapshot, hud_records))
        self.last_vehicle_type = snapshot.vehicle_type or self.last_vehicle_type
        return self._filter(events), self._map_strength(snapshot)

    def _detect_cas(self, snapshot: TelemetrySnapshot) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        if self.base_mode == "tank" and snapshot.vehicle_type == "aircraft" and not self.in_cas:
            self.in_cas = True
            self.g_band = 0
            events.append(self._event("war_thunder.cas_enter", snapshot))
        elif self.in_cas and snapshot.vehicle_type == "tank":
            self.in_cas = False
            self.g_band = 0
            events.append(self._event("war_thunder.cas_exit", snapshot))
        return events

    def _detect_repair(self, snapshot: TelemetrySnapshot) -> list[DetectedEvent]:
        if snapshot.vehicle_type != "tank":
            return []
        if snapshot.repairing and not self.repairing:
            self.repairing = True
            return [self._event("war_thunder.tank_repair_start", snapshot)]
        if not snapshot.repairing and self.repairing:
            self.repairing = False
            return [self._event("war_thunder.tank_repair_end", snapshot)]
        return []

    def _detect_bands(self, snapshot: TelemetrySnapshot) -> list[DetectedEvent]:
        if snapshot.vehicle_type == "aircraft":
            new_band = _band(snapshot.gforce, GFORCE_THRESHOLDS, self.g_band, GFORCE_HYSTERESIS)
            event = None
            if new_band > self.g_band:
                key = ("medium", "high", "extreme")[new_band - 1]
                event = self._event(f"war_thunder.aircraft_g_{key}", snapshot)
            self.g_band = new_band
            return [event] if event else []

        if snapshot.vehicle_type == "tank":
            speed = abs(snapshot.speed_kmh)
            new_band = _band(speed, SPEED_THRESHOLDS, self.speed_band, SPEED_HYSTERESIS)
            event = None
            if new_band > self.speed_band:
                key = ("low", "medium", "high")[new_band - 1]
                event = self._event(f"war_thunder.tank_speed_{key}", snapshot)
            self.speed_band = new_band
            return [event] if event else []
        return []

    def _detect_hud(self, snapshot: TelemetrySnapshot, records: list[HudRecord]) -> list[DetectedEvent]:
        player = self.settings.player_name
        if not player or player == "请填写游戏昵称":
            return []
        mode = snapshot.vehicle_type or self.last_vehicle_type or self.base_mode
        if mode not in {"aircraft", "tank"}:
            return []

        events: list[DetectedEvent] = []
        for record in records:
            result = classify_combat_message(record.message, player)
            if result in {"kill", "death"}:
                events.append(
                    DetectedEvent(
                        event_key=f"war_thunder.{mode}_{result}",
                        match_value=str(record.record_id),
                        data={"message": record.message, "vehicleType": mode},
                    )
                )
        return events

    def _map_strength(self, snapshot: TelemetrySnapshot) -> ContinuousOutput:
        if snapshot.vehicle_type == "aircraft":
            ratio = _linear(snapshot.gforce, GFORCE_MIN, GFORCE_MAX)
            if snapshot.gforce >= GFORCE_THRESHOLDS[2]:
                event_key = "war_thunder.aircraft_g_extreme"
            elif snapshot.gforce >= GFORCE_THRESHOLDS[1]:
                event_key = "war_thunder.aircraft_g_high"
            else:
                event_key = "war_thunder.aircraft_g_medium"
            return ContinuousOutput(ratio=ratio, event_key=event_key if ratio > 0 else "")

        if snapshot.vehicle_type == "tank":
            speed = abs(snapshot.speed_kmh)
            ratio = _linear(speed, SPEED_MIN, SPEED_MAX)
            if speed >= SPEED_THRESHOLDS[2]:
                event_key = "war_thunder.tank_speed_high"
            elif speed >= SPEED_THRESHOLDS[1]:
                event_key = "war_thunder.tank_speed_medium"
            else:
                event_key = "war_thunder.tank_speed_low"
            return ContinuousOutput(ratio=ratio, event_key=event_key if ratio > 0 else "")
        return ContinuousOutput()

    def _event(self, key: str, snapshot: TelemetrySnapshot) -> DetectedEvent:
        return DetectedEvent(
            event_key=key,
            data={
                "vehicleType": snapshot.vehicle_type,
                "vehicleName": snapshot.vehicle_name,
                "gforce": round(snapshot.gforce, 2),
                "speedKmh": round(snapshot.speed_kmh, 1),
                "repairTimeS": round(snapshot.repair_time_s, 1),
            },
        )

    def _filter(self, events: list[DetectedEvent]) -> list[DetectedEvent]:
        now = self.clock()
        accepted: list[DetectedEvent] = []
        for event in events:
            last = self._last_event_at.get(event.event_key, float("-inf"))
            if now - last >= MINIMUM_EVENT_INTERVAL_S:
                self._last_event_at[event.event_key] = now
                accepted.append(event)
        return accepted

    def _reset_battle(self) -> None:
        self.battle_active = False
        self.base_mode = ""
        self.in_cas = False
        self.repairing = False
        self.last_vehicle_type = ""
        self.g_band = 0
        self.speed_band = 0


def classify_combat_message(message: str, player_name: str) -> str | None:
    """按玩家名在击毁语句中的位置区分击杀和死亡。"""
    cleaned = ZERO_WIDTH.sub("", message).casefold()
    player = ZERO_WIDTH.sub("", player_name).casefold().strip()
    if not player or player not in cleaned:
        return None

    player_pos = cleaned.find(player)
    for verb in KILL_VERBS:
        verb_pos = cleaned.find(verb.casefold())
        if verb_pos < 0:
            continue
        return "kill" if player_pos < verb_pos else "death"
    if any(verb.casefold() in cleaned for verb in CRASH_VERBS):
        return "death"
    return None


def _band(value: float, thresholds: tuple[float, float, float], current: int, hysteresis: float) -> int:
    target = sum(value >= threshold for threshold in thresholds)
    if target >= current:
        return target
    # 降档时使用迟滞，避免临界值上下抖动反复触发。
    while current > 0 and value < thresholds[current - 1] - hysteresis:
        current -= 1
    return current


def _linear(value: float, minimum: float, maximum: float) -> float:
    if value <= minimum:
        return 0.0
    if value >= maximum:
        return 1.0
    return (value - minimum) / (maximum - minimum)
