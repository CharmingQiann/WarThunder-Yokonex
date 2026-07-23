from __future__ import annotations

import unittest
from pathlib import Path

from war_thunder_yokonex.config import load_settings


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_default_config_is_valid(self) -> None:
        settings = load_settings(ROOT / "config.json")
        self.assertEqual(settings.player_name, "请填写游戏昵称")


if __name__ == "__main__":
    unittest.main()
