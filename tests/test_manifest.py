from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def test_manifest_contains_all_reference_features(self) -> None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        keys = {event["eventKey"] for event in manifest["yokonex"]["events"]}
        required = {
            "war_thunder.aircraft_g_medium",
            "war_thunder.aircraft_kill",
            "war_thunder.aircraft_death",
            "war_thunder.tank_speed_low",
            "war_thunder.tank_kill",
            "war_thunder.tank_death",
            "war_thunder.tank_repair_start",
            "war_thunder.tank_repair_end",
            "war_thunder.cas_enter",
            "war_thunder.cas_exit",
        }
        self.assertTrue(required <= keys)
        self.assertEqual(len(keys), len(manifest["yokonex"]["events"]))
        self.assertEqual(manifest["entry"], "WarThunder-Yokonex-Plugin.exe")
        self.assertEqual(manifest["author"], "栖安")
        self.assertEqual(manifest["version"], "1.1.3")
        commands = {event["eventKey"]: event["commandId"] for event in manifest["yokonex"]["events"]}
        self.assertEqual(commands["war_thunder.battle_start"], "_stop_all")
        self.assertEqual(commands["war_thunder.battle_end"], "_stop_all")
        self.assertTrue(
            all("-" not in command for command in commands.values()),
            "默认 commandId 应与现有插件统一使用下划线",
        )


if __name__ == "__main__":
    unittest.main()
