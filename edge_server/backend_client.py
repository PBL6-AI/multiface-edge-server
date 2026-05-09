from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(
        self,
        backend_url: str,
        edge_token: str,
        retry_attempts: int = 5,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        self._backend_url = backend_url.rstrip("/")
        self._edge_token = edge_token
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)

    def register_device(self, payload: dict[str, Any]) -> None:
        self._post("/edge/devices/register", payload)

    def send_heartbeat(self, payload: dict[str, Any]) -> None:
        self._post("/edge/devices/heartbeat", payload)

    def check_connectivity(self) -> None:
        response = requests.get(self._backend_url, timeout=(3, 10))
        logger.info(
            "Backend reachability check returned status %s for %s",
            response.status_code,
            self._backend_url,
        )

    def _post(self, path: str, payload: dict[str, Any]) -> None:
        headers = {"content-type": "application/json"}
        if self._edge_token:
            headers["x-edge-token"] = self._edge_token

        last_error: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                response = requests.post(
                    f"{self._backend_url}{path}",
                    json=payload,
                    headers=headers,
                    timeout=(3, 10),
                )
                response.raise_for_status()
                logger.debug("POST %s succeeded", path)
                return
            except requests.RequestException as exc:
                last_error = exc
                response_text = ""
                if exc.response is not None:
                    response_text = exc.response.text[:500]
                logger.warning(
                    "POST %s failed on attempt %s/%s: %s%s",
                    path,
                    attempt,
                    self._retry_attempts,
                    exc,
                    f" | response={response_text}" if response_text else "",
                )
                if attempt < self._retry_attempts:
                    time.sleep(self._retry_delay_seconds)

        assert last_error is not None
        raise last_error
