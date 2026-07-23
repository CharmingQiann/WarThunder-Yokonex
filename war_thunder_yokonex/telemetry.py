from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .models import HudRecord, TelemetrySnapshot


class WarThunderClient:
    """读取战争雷霆只监听本机的 8111 遥测接口。"""

    def __init__(self, timeout: float, base_url: str = "http://127.0.0.1:8111") -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.logger = logging.getLogger("war_thunder.telemetry")
        self._last_damage_id = 0
        self._hud_seeded = False

    def fetch_snapshot(self) -> TelemetrySnapshot:
        state = self._get_json("/state")
        indicators = self._get_json("/indicators")
        if not isinstance(state, dict) and not isinstance(indicators, dict):
            return TelemetrySnapshot()

        state = state if isinstance(state, dict) else {}
        indicators = indicators if isinstance(indicators, dict) else {}
        vehicle_type = detect_vehicle_type(state, indicators)
        active = _valid_for_vehicle(vehicle_type, state, indicators)
        gforce = abs(_number(state.get("Ny", state.get("ny", indicators.get("g_meter", 0)))))
        speed = _extract_speed(vehicle_type, state, indicators)
        repairing = _number(indicators.get("is_repairing", 0)) > 0
        repair_time = max(0.0, _number(indicators.get("repair_time", 0)))
        vehicle_name = str(indicators.get("type") or state.get("type") or "")
        return TelemetrySnapshot(
            connected=True,
            active=active,
            vehicle_type=vehicle_type,
            vehicle_name=vehicle_name,
            gforce=gforce,
            speed_kmh=speed,
            repairing=repairing,
            repair_time_s=repair_time,
            raw_state=state,
            raw_indicators=indicators,
        )

    def fetch_hud_records(self) -> list[HudRecord]:
        previous_last_id = self._last_damage_id
        query = urllib.parse.urlencode({"lastEvt": 0, "lastDmg": self._last_damage_id})
        data = self._get_json(f"/hudmsg?{query}")
        if not isinstance(data, dict):
            return []
        records: list[HudRecord] = []
        for item in data.get("damage", []):
            if not isinstance(item, dict):
                continue
            record_id = int(item.get("id", 0) or 0)
            self._last_damage_id = max(self._last_damage_id, record_id)
            if record_id > previous_last_id:
                records.append(HudRecord(record_id=record_id, message=str(item.get("msg", ""))))

        # 第一次连接只记录游标，防止把上一局历史消息当成新事件。
        if not self._hud_seeded:
            self._hud_seeded = True
            return []
        return records

    def reset_hud_cursor(self) -> None:
        """游戏进程重启后 HUD 编号会归零，下次读取先重新建立游标。"""
        self._last_damage_id = 0
        self._hud_seeded = False

    def _get_json(self, path: str) -> Any | None:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json", "User-Agent": "Yokonex-WarThunder/1.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None


def detect_vehicle_type(state: dict[str, Any], indicators: dict[str, Any]) -> str:
    army = str(indicators.get("army", "")).lower()
    if army == "tank":
        return "tank"
    if army in {"aircraft", "plane"}:
        return "aircraft"

    indicator_type = str(indicators.get("type", "")).lower()
    if indicator_type.startswith(("tank", "groundmodels/", "tankmodels/")):
        return "tank"
    if indicator_type.startswith(("aircraft", "plane")):
        return "aircraft"

    state_keys = {key.lower() for key in state}
    if state_keys & {"ny", "aoa, deg", "ias, km/h", "tas, km/h", "vy, m/s"}:
        return "aircraft"

    indicator_keys = {key.lower() for key in indicators}
    tank_fields = {
        "gunner_state", "driver_state", "commander_state", "loader_state",
        "crew_total", "first_stage_ammo", "is_repairing", "repair_time",
    }
    if indicator_keys & tank_fields:
        return "tank"
    return ""


def _valid_for_vehicle(vehicle_type: str, state: dict[str, Any], indicators: dict[str, Any]) -> bool:
    if vehicle_type == "tank":
        return _truthy_valid(indicators.get("valid", False))
    if vehicle_type == "aircraft":
        return _truthy_valid(state.get("valid", indicators.get("valid", False)))
    return False


def _truthy_valid(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    return bool(value)


def _extract_speed(vehicle_type: str, state: dict[str, Any], indicators: dict[str, Any]) -> float:
    if vehicle_type == "tank":
        return _number(indicators.get("speed", state.get("speed", 0)))
    return _number(state.get("IAS, km/h", state.get("TAS, km/h", indicators.get("speed", 0))))


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
