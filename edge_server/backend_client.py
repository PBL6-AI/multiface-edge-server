from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(self, backend_url: str, edge_token: str) -> None:
        self._backend_url = backend_url.rstrip("/")
        self._edge_token = edge_token

    def register_device(self, payload: dict[str, Any]) -> None:
        self._post("/edge/devices/register", payload)

    def send_heartbeat(self, payload: dict[str, Any]) -> None:
        self._post("/edge/devices/heartbeat", payload)

    def _post(self, path: str, payload: dict[str, Any]) -> None:
        headers = {"content-type": "application/json"}
        if self._edge_token:
          headers["x-edge-token"] = self._edge_token

        response = requests.post(
            f"{self._backend_url}{path}",
            json=payload,
            headers=headers,
            timeout=(3, 10),
        )
        response.raise_for_status()
        logger.debug("POST %s succeeded", path)
