from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from war_thunder_yokonex.config import load_settings
from war_thunder_yokonex.detector import EventDetector, classify_combat_message
from war_thunder_yokonex.models import HudRecord, TelemetrySnapshot


ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


def snap(vehicle: str, **updates) -> TelemetrySnapshot:
    data = {
        "connected": True,
        "active": True,
        "vehicle_type": vehicle,
        "vehicle_name": "fixture",
    }
    data.update(updates)
    return TelemetrySnapshot(**data)


class DetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        loaded = load_settings(ROOT / "config.json")
        self.settings = replace(loaded, player_name="TestPilot")
        self.clock = FakeClock()
        self.detector = EventDetector(self.settings, self.clock)

    def keys(self, snapshot: TelemetrySnapshot, records=None) -> list[str]:
        events, _ = self.detector.process(snapshot, records)
        self.clock.advance()
        return [event.event_key for event in events]

    def test_aircraft_gforce_and_strength(self) -> None:
        keys = self.keys(snap("aircraft", gforce=3.5, speed_kmh=450))
        self.assertEqual(keys, ["war_thunder.battle_start", "war_thunder.aircraft_g_medium"])
        events, strength = self.detector.process(snap("aircraft", gforce=9.5))
        self.assertIn("war_thunder.aircraft_g_extreme", [event.event_key for event in events])
        self.assertGreater(strength.ratio, 0.9)
        self.assertEqual(strength.event_key, "war_thunder.aircraft_g_extreme")

    def test_tank_speed_repair_and_strength(self) -> None:
        keys = self.keys(snap("tank", speed_kmh=12, repairing=True, repair_time_s=18))
        self.assertEqual(
            keys,
            ["war_thunder.battle_start", "war_thunder.tank_repair_start", "war_thunder.tank_speed_low"],
        )
        events, strength = self.detector.process(snap("tank", speed_kmh=55, repairing=False))
        keys = [event.event_key for event in events]
        self.assertIn("war_thunder.tank_repair_end", keys)
        self.assertIn("war_thunder.tank_speed_high", keys)
        self.assertGreater(strength.ratio, 0.9)
        self.assertEqual(strength.event_key, "war_thunder.tank_speed_high")

    def test_tank_cas_switches_to_gforce(self) -> None:
        self.keys(snap("tank", speed_kmh=20))
        keys = self.keys(snap("aircraft", gforce=5))
        self.assertIn("war_thunder.cas_enter", keys)
        self.assertIn("war_thunder.aircraft_g_medium", keys)
        keys = self.keys(snap("tank", speed_kmh=0))
        self.assertIn("war_thunder.cas_exit", keys)

    def test_battle_end_resets_output(self) -> None:
        self.keys(snap("aircraft", gforce=5))
        events, strength = self.detector.process(TelemetrySnapshot(connected=True))
        self.assertEqual([event.event_key for event in events], ["war_thunder.battle_end"])
        self.assertEqual(strength.ratio, 0)

    def test_hud_kill_and_death_for_both_modes(self) -> None:
        player = self.settings.player_name
        self.keys(snap("aircraft"))
        records = [HudRecord(1, f"{player} (F-16) 击落了 Enemy (MiG-29)")]
        self.assertIn("war_thunder.aircraft_kill", self.keys(snap("aircraft"), records))

        # 新战斗中用坦克消息验证陆战死亡事件。
        self.keys(TelemetrySnapshot(connected=True))
        self.keys(snap("tank"))
        records = [HudRecord(2, f"Enemy (T-80) 击毁了 {player} (M1A2)")]
        self.assertIn("war_thunder.tank_death", self.keys(snap("tank"), records))

    def test_combat_message_supports_english_and_crash(self) -> None:
        self.assertEqual(classify_combat_message("Alice (Spitfire) shot down Bob", "Alice"), "kill")
        self.assertEqual(classify_combat_message("Bob destroyed Alice (Tank)", "Alice"), "death")
        self.assertEqual(classify_combat_message("Alice has crashed", "Alice"), "death")


if __name__ == "__main__":
    unittest.main()
