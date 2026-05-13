"""Bridge local state persistence.

Stores machine_id (Studio-generated, stable across restarts) and session token
in a JSON file so the daemon can resume without re-handshaking from scratch.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class BridgeState:
    machine_id: Optional[str] = None
    token: Optional[str] = None

    @staticmethod
    def load(dir_path: str) -> "BridgeState":
        path = os.path.join(dir_path, "state.json")
        os.makedirs(dir_path, exist_ok=True)
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return BridgeState(
                machine_id=data.get("machine_id"),
                token=data.get("token"),
            )
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
            logger.info("state.json not found or invalid, starting fresh: %s", exc)
            return BridgeState()

    def save(self, dir_path: str) -> None:
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, "state.json")
        data: Dict[str, object] = {
            "machine_id": self.machine_id,
            "token": self.token,
        }
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
