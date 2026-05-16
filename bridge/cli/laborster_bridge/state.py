"""Single 0600 JSON file holding all persisted state and secrets.

Schema::

    {
      "username":     "<studio account username>",
      "machine_id":   "m_xxxx",          # assigned by Studio on first handshake
      "bridge_id":    "br_xxxx",
      "studio_token": "<bridge session token>",   # cleared on 401 / logout
      "channels": [
        { "username": "<chat account>", "chat_token": "<chat session token>" }
      ]
    }

No password is ever stored — only tokens, mirroring the browser session
model on both the Studio and the Chat side.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from . import config


def load() -> dict[str, Any]:
    path = config.state_file()
    if not path.exists():
        return {"channels": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("channels", [])
    return data


def save(data: dict[str, Any]) -> None:
    path = config.state_file()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".laborster.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
