from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """击杀和死亡识别只需要玩家昵称。"""

    player_name: str


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def load_settings(path: Path | None = None) -> Settings:
    config_path = path or runtime_root() / "config.json"
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    return Settings(
        player_name=str(raw.get("player_name", "")).strip(),
    )
