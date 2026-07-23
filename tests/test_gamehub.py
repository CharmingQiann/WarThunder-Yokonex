from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from war_thunder_yokonex.gamehub import (
    GameHubContinuousOutput,
    GameHubEventClient,
    waveform_strength_peaks,
)
from war_thunder_yokonex.models import DetectedEvent


class GatewayHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/bluetooth/studio":
            self._json(
                200,
                {
                    "ems_waveforms": [
                        {
                            "id": "ems-flight",
                            "steps": [
                                {"channel_a": 25, "channel_b": 10},
                                {"channel_a": 70, "channel_b": 40},
                            ],
                        }
                    ],
                    "toy_waveforms": [],
                    "mappings": [
                        {
                            "command_id": "wt_air_g_high",
                            "waveform_id": "ems-flight",
                            "device_id": "device-a",
                            "enabled": True,
                        }
                    ],
                },
            )
            return
        if self.path.endswith("/adapter-config"):
            self._json(
                200,
                {
                    "source": "war_thunder",
                    "enabled": True,
                    "mappings": {"war_thunder.aircraft_kill": "custom-kill"},
                },
            )
            return
        self._json(404, {})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.received.append(payload)
        self._json(202, {"accepted": True, "eventId": payload["eventId"]})

    def log_message(self, _format: str, *_args) -> None:
        pass

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GameHubTests(unittest.TestCase):
    def setUp(self) -> None:
        GatewayHandler.received = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_uses_gamehub_mapping_and_sends_valid_event(self) -> None:
        host, port = self.server.server_address
        client = GameHubEventClient(timeout=1, base_url=f"http://{host}:{port}")
        self.assertTrue(client.refresh_config())
        self.assertTrue(
            client.send_event(
                DetectedEvent("war_thunder.aircraft_kill", {"vehicleType": "aircraft"}, "hud-10")
            )
        )
        deadline = time.monotonic() + 2
        while not GatewayHandler.received and time.monotonic() < deadline:
            time.sleep(0.01)
        client.stop()
        payload = GatewayHandler.received[0]
        self.assertEqual(payload["source"], "war_thunder")
        self.assertEqual(payload["commandId"], "custom-kill")
        self.assertEqual(payload["matchValue"], "hud-10")
        self.assertTrue(payload["occurredAt"].endswith("+00:00"))

    def test_rejects_non_local_gateway_url(self) -> None:
        with self.assertRaises(ValueError):
            GameHubEventClient(timeout=1, base_url="http://192.168.1.20:43002")

    def test_continuous_cap_comes_from_waveform_strength(self) -> None:
        ems = {
            "steps": [
                {"channel_a": 20, "channel_b": 10},
                {"channel_a": 60, "channel_b": 35},
            ]
        }
        toy = {
            "steps": [
                {"motor_a": 4, "motor_b": 8},
                {"motor_a": 12, "motor_b": 6},
            ]
        }
        self.assertEqual(waveform_strength_peaks(ems), (60, 35))
        self.assertEqual(waveform_strength_peaks(toy), (12, 8))

    def test_continuous_target_uses_command_waveform_mapping(self) -> None:
        host, port = self.server.server_address
        output = GameHubContinuousOutput(
            base_url=f"http://{host}:{port}",
            manifest_path=Path(__file__).resolve().parents[1] / "manifest.json",
            interval_ms=150,
            timeout=1,
        )
        self.assertEqual(output._fetch_waveform_targets("wt_air_g_high"), [("device-a", 70, 40)])


if __name__ == "__main__":
    unittest.main()
