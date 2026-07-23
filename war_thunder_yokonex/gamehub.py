from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ContinuousOutput, DetectedEvent


class GameHubEventClient:
    """读取 GameHub 中用户配置的映射，并提交离散游戏事件。"""

    SOURCE = "war_thunder"

    def __init__(self, timeout: float, base_url: str | None = None) -> None:
        environment_url = os.environ.get("YOKONEX_GATEWAY_URL", "").strip()
        self.base_url = _normalize_gateway_url(base_url or environment_url or "http://127.0.0.1:43002")
        self.timeout = timeout
        self.enabled = False
        self.mappings: dict[str, str] = {}
        self.session_id = f"wt-{uuid.uuid4().hex}"
        self.logger = logging.getLogger("war_thunder.gamehub")
        self._events: queue.Queue[tuple[float, dict[str, Any]] | None] = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._send_loop, name="GameHubEvents", daemon=True)
        self._worker.start()

    def refresh_config(self) -> bool:
        data = self._request_json("GET", f"/v1/game-integrations/{self.SOURCE}/adapter-config")
        if not isinstance(data, dict):
            self.enabled = False
            self.mappings = {}
            return False
        self.enabled = bool(data.get("enabled"))
        raw_mappings = data.get("mappings")
        self.mappings = {
            str(key): str(value).strip()
            for key, value in (raw_mappings.items() if isinstance(raw_mappings, dict) else [])
            if str(value).strip()
        }
        return True

    def send_event(self, event: DetectedEvent) -> bool:
        command_id = self.mappings.get(event.event_key)
        if not self.enabled or not command_id:
            return False
        payload: dict[str, Any] = {
            "source": self.SOURCE,
            "eventKey": event.event_key,
            "commandId": command_id,
            "occurredAt": datetime.now(timezone.utc).isoformat(),
            "eventId": f"{self.session_id}-{uuid.uuid4().hex}",
            "sessionId": self.session_id,
            "data": event.data,
        }
        if event.match_value is not None:
            payload["matchValue"] = event.match_value
        try:
            self._events.put_nowait((time.monotonic(), payload))
            return True
        except queue.Full:
            self.logger.warning("GameHub 事件队列已满：%s", event.event_key)
            return False

    def stop(self) -> None:
        self._stop.set()
        try:
            self._events.put_nowait(None)
        except queue.Full:
            pass
        self._worker.join(timeout=2)
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                break

    def _send_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pending = self._events.get(timeout=0.2)
            except queue.Empty:
                continue
            if pending is None:
                break
            queued_at, payload = pending
            # 与现有插件一致：旧事件直接丢弃，网关恢复后不补发过期反馈。
            if time.monotonic() - queued_at > 3:
                continue
            result = self._request_json("POST", "/v1/events", payload)
            event_key = str(payload.get("eventKey", ""))
            self._log_delivery(event_key, result)

    def _log_delivery(self, event_key: str, result: Any | None) -> bool:
        accepted = isinstance(result, dict) and bool(result.get("accepted"))
        if accepted:
            self.logger.info("GameHub 已接收事件：%s", event_key)
        elif isinstance(result, dict):
            self.logger.warning("事件被 GameHub 跳过：%s %s", event_key, result.get("code", ""))
        return accepted

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any | None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                return json.load(exc)
            except (json.JSONDecodeError, OSError):
                return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None


def _normalize_gateway_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("YOKONEX_GATEWAY_URL 格式错误") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ValueError("YOKONEX_GATEWAY_URL 必须是 127.0.0.1 的 HTTP 地址")
    return f"http://127.0.0.1:{port}"


class GameHubContinuousOutput:
    """以 GameHub 中 commandId 对应波形的 A/B 强度作为连续输出上限。"""

    def __init__(
        self,
        base_url: str,
        manifest_path: Path,
        interval_ms: int,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.manifest_path = manifest_path
        self.interval = interval_ms / 1000
        self.timeout = timeout
        self.logger = logging.getLogger("war_thunder.output")
        self._output = ContinuousOutput()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="GameHubOutput", daemon=True)
        self._thread.start()

    def update(self, output: ContinuousOutput) -> None:
        with self._lock:
            self._output = output

    def stop(self) -> None:
        self.update(ContinuousOutput())
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        delay = 0.5
        while not self._stop.is_set():
            try:
                self._connection_loop()
                delay = 0.5
            except Exception as exc:
                self.logger.debug("连续输出连接已断开：%s", exc)
                self._stop.wait(delay)
                delay = min(5.0, delay * 2)

    def _connection_loop(self) -> None:
        from websockets.sync.client import connect

        token = self._fetch_token()
        ws_base = self.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        url = f"{ws_base}/ws/plugin?{urllib.parse.urlencode({'token': token})}"
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8-sig"))
        hello_manifest = {
            key: manifest[key]
            for key in ("id", "name", "version", "sdk", "author", "description")
            if key in manifest
        }
        with connect(url, open_timeout=self.timeout, close_timeout=1) as websocket:
            websocket.send(json.dumps({"op": "hello", "token": token, "manifest": hello_manifest}, ensure_ascii=False))
            ack = json.loads(websocket.recv(timeout=self.timeout))
            if not ack.get("accepted"):
                raise RuntimeError(str(ack.get("reason") or "GameHub 插件握手失败"))
            websocket.recv(timeout=self.timeout)  # config
            self.logger.info("连续强度通道已连接")
            targets: list[tuple[str, int, int]] = []
            active_command_id = ""
            next_target_refresh = 0.0
            while not self._stop.wait(self.interval):
                with self._lock:
                    output = self._output

                if output.command_id != active_command_id:
                    self._send_targets(websocket, targets, 0.0)
                    active_command_id = output.command_id
                    targets = self._fetch_waveform_targets(active_command_id) if active_command_id else []
                    next_target_refresh = time.monotonic() + 2
                elif active_command_id and time.monotonic() >= next_target_refresh:
                    try:
                        targets = self._fetch_waveform_targets(active_command_id)
                    except Exception as exc:
                        self.logger.debug("波形映射刷新失败，继续使用上次结果：%s", exc)
                    next_target_refresh = time.monotonic() + 2
                self._send_targets(websocket, targets, output.ratio)

            self._send_targets(websocket, targets, 0.0)

    def _fetch_token(self) -> str:
        request = urllib.request.Request(f"{self.base_url}/v1/plugins/_session_token")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            token = str(json.load(response).get("token", ""))
        if not token:
            raise RuntimeError("GameHub 未返回插件 token")
        return token

    def _fetch_waveform_targets(self, command_id: str) -> list[tuple[str, int, int]]:
        request = urllib.request.Request(f"{self.base_url}/v1/bluetooth/studio")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            studio = json.load(response)
        if not isinstance(studio, dict):
            return []

        waveform_items = [*studio.get("ems_waveforms", []), *studio.get("toy_waveforms", [])]
        waveforms = {
            str(item.get("id", "")): item
            for item in waveform_items
            if isinstance(item, dict) and item.get("id")
        }
        targets: list[tuple[str, int, int]] = []
        for mapping in studio.get("mappings", []):
            if (
                not isinstance(mapping, dict)
                or str(mapping.get("command_id", "")) != command_id
                or not bool(mapping.get("enabled", True))
            ):
                continue
            waveform = waveforms.get(str(mapping.get("waveform_id", "")))
            if waveform is None:
                continue
            peak_a, peak_b = waveform_strength_peaks(waveform)
            if peak_a > 0 or peak_b > 0:
                targets.append((str(mapping.get("device_id", "")), peak_a, peak_b))
        return targets

    @staticmethod
    def _send_targets(websocket: Any, targets: list[tuple[str, int, int]], ratio: float) -> None:
        normalized = max(0.0, min(1.0, float(ratio)))
        for device_id, peak_a, peak_b in targets:
            for channel, peak in (("a", peak_a), ("b", peak_b)):
                # 连续遥测只做比例缩放，最终上限完全来自用户选择的波形。
                native_value = round(peak * normalized)
                websocket.send(json.dumps({
                    "op": "set_strength",
                    "channel": channel,
                    "pct": native_value,
                    "device_id": device_id,
                }))


def waveform_strength_peaks(waveform: dict[str, Any]) -> tuple[int, int]:
    steps = waveform.get("steps")
    if not isinstance(steps, list):
        return 0, 0
    peak_a = 0
    peak_b = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        if "channel_a" in step or "channel_b" in step:
            peak_a = max(peak_a, _nonnegative_int(step.get("channel_a")))
            peak_b = max(peak_b, _nonnegative_int(step.get("channel_b")))
        else:
            peak_a = max(peak_a, _nonnegative_int(step.get("motor_a")))
            peak_b = max(peak_b, _nonnegative_int(step.get("motor_b")))
    return peak_a, peak_b


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
