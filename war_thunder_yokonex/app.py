from __future__ import annotations

import atexit
import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

from .config import load_settings, runtime_root
from .detector import EventDetector
from .gamehub import GameHubContinuousOutput, GameHubEventClient
from .models import ContinuousOutput
from .single_instance import SingleInstance
from .telemetry import WarThunderClient


POLL_INTERVAL_S = 0.2
HUD_INTERVAL_S = 0.5
GAMEHUB_CONFIG_REFRESH_S = 2.0
REQUEST_TIMEOUT_S = 0.45
CONTINUOUS_OUTPUT_INTERVAL_MS = 150


def main() -> None:
    root = runtime_root()
    _configure_logging(root)
    logger = logging.getLogger("war_thunder")
    instance = SingleInstance("Local\\WarThunder-Yokonex-Plugin")
    if not instance.acquired:
        logger.info("战争雷霆联动已有实例运行，本次启动直接结束")
        return
    atexit.register(instance.close)
    try:
        settings = load_settings(root / "config.json")
    except Exception as exc:
        logger.error("配置加载失败：%s", exc)
        raise SystemExit(2) from exc

    telemetry = WarThunderClient(REQUEST_TIMEOUT_S)
    gamehub = GameHubEventClient(REQUEST_TIMEOUT_S)
    detector = EventDetector(settings)
    output = GameHubContinuousOutput(
        base_url=gamehub.base_url,
        manifest_path=root / "manifest.json",
        interval_ms=CONTINUOUS_OUTPUT_INTERVAL_MS,
        timeout=REQUEST_TIMEOUT_S,
    )

    running = True

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    output.start()

    logger.info("役次元战争雷霆联动已启动，等待游戏与 GameHub")
    next_config_refresh = 0.0
    next_hud_poll = 0.0
    hud_records = []
    poll_interval = POLL_INTERVAL_S

    try:
        while running:
            started = time.monotonic()
            if started >= next_config_refresh:
                gamehub.refresh_config()
                next_config_refresh = started + GAMEHUB_CONFIG_REFRESH_S

            snapshot = telemetry.fetch_snapshot()
            if snapshot.connected and started >= next_hud_poll:
                hud_records = telemetry.fetch_hud_records()
                next_hud_poll = started + HUD_INTERVAL_S
            else:
                hud_records = []
                if not snapshot.connected:
                    telemetry.reset_hud_cursor()

            events, continuous = detector.process(snapshot, hud_records)
            if gamehub.enabled and continuous.event_key:
                continuous = ContinuousOutput(
                    ratio=continuous.ratio,
                    event_key=continuous.event_key,
                    command_id=gamehub.mappings.get(continuous.event_key, ""),
                )
            else:
                continuous = ContinuousOutput()
            output.update(continuous)

            for event in events:
                if gamehub.send_event(event):
                    logger.info("事件已进入发送队列：%s", event.event_key)

            elapsed = time.monotonic() - started
            time.sleep(max(0.02, poll_interval - elapsed))
    finally:
        output.stop()
        gamehub.stop()
        logger.info("役次元战争雷霆联动已停止")


def _configure_logging(root) -> None:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(
        log_dir / "war-thunder-yokonex.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
