"""Fixtures for the live-stack integration tests.

No mocks: these drive laborster_bridge.studio_client.StudioClient against a
real, running Studio (user-api) + admin-api. They run only when both
STUDIO_BASE_URL and ADMIN_BASE_URL are set — CI sets them when it runs this
package inside the bridge-host container, which already sits on the compose
network with the sidecar package installed.
"""

from __future__ import annotations

import os
import uuid

import pytest

from laborster_bridge import config
from laborster_bridge.http import request_json

STUDIO_URL = os.environ.get("STUDIO_BASE_URL")
ADMIN_URL = os.environ.get("ADMIN_BASE_URL")


@pytest.fixture(autouse=True)
def _point_config_at_stack() -> None:
    # StudioClient reads config.STUDIO_BASE_URL at call time; aim it at the
    # live user-api. The top-level conftest restores the global afterwards.
    if STUDIO_URL:
        config.set_studio_base_url(STUDIO_URL)


@pytest.fixture
def account() -> dict:
    """Mint a fresh Studio account via admin-api.

    That plane carries no in-app auth — it's edge-gated by Cloudflare Access
    and open on the internal compose network, so a plain POST works here.
    """
    username = f"it-{uuid.uuid4().hex[:8]}"
    password = "pw-" + uuid.uuid4().hex[:12]
    created = request_json(
        "POST",
        f"{ADMIN_URL}/api/admin/accounts",
        body={"username": username, "password": password, "display_name": username},
    )
    return {"id": created["id"], "username": username, "password": password}
