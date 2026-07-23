from __future__ import annotations

import unittest

from war_thunder_yokonex.telemetry import WarThunderClient, detect_vehicle_type


class TelemetryTests(unittest.TestCase):
    def test_detects_aircraft_from_state(self) -> None:
        self.assertEqual(detect_vehicle_type({"valid": True, "Ny": 3.2, "IAS, km/h": 500}, {}), "aircraft")

    def test_detects_tank_from_indicators(self) -> None:
        indicators = {"valid": True, "type": "tankModels/us_m4", "driver_state": 0}
        self.assertEqual(detect_vehicle_type({"valid": False}, indicators), "tank")

    def test_hud_first_read_seeds_and_duplicate_id_is_ignored(self) -> None:
        client = WarThunderClient(timeout=0.1)
        replies = [
            {"damage": [{"id": 10, "msg": "old"}]},
            {"damage": [{"id": 10, "msg": "old"}, {"id": 11, "msg": "new"}]},
            {"damage": [{"id": 11, "msg": "new"}]},
        ]
        client._get_json = lambda _path: replies.pop(0)  # type: ignore[method-assign]
        self.assertEqual(client.fetch_hud_records(), [])
        self.assertEqual([item.message for item in client.fetch_hud_records()], ["new"])
        self.assertEqual(client.fetch_hud_records(), [])


if __name__ == "__main__":
    unittest.main()
