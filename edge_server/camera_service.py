from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Optional

from .backend_client import BackendClient
from .config import EdgeServerConfig
from .rtsp_publisher import RtspPublisher

logger = logging.getLogger(__name__)


@dataclass
class EdgeRuntimeState:
    is_running: bool = False
    session_id: Optional[int] = None
    camera_id: Optional[str] = None
    stream_url: Optional[str] = None
    fps: Optional[int] = None
    last_error: Optional[str] = None
    last_started_at: Optional[str] = None


class CameraEdgeService:
    def __init__(self, config: EdgeServerConfig, backend_client: BackendClient) -> None:
        self._config = config
        self._backend_client = backend_client
        self._publisher = RtspPublisher(config)
        self._lock = Lock()
        self._heartbeat_stop = Event()
        self._heartbeat_thread: Optional[Thread] = None
        self._state = EdgeRuntimeState(camera_id=config.camera_id, fps=config.target_fps)

    def register(self) -> None:
        payload = {
            "deviceCode": self._config.device_code,
            "deviceName": self._config.device_name,
            "roomCode": self._config.room_code,
            "cameraId": self._config.camera_id,
            "controlBaseUrl": self._config.control_base_url,
            "streamBaseUrl": self._config.stream_base_url,
            "metadata": {
                "publisher": "mediamtx",
                "targetFps": self._config.target_fps,
                "resolution": f"{self._config.frame_width}x{self._config.frame_height}",
            },
        }
        self._backend_client.register_device(payload)

    def start(self, session_id: int, camera_id: str | None = None) -> dict:
        with self._lock:
            if self._state.is_running and self._state.session_id != session_id:
                raise RuntimeError(
                    f"Edge device is already running session {self._state.session_id}"
                )

            stream_path = f"{self._config.device_code}/session-{session_id}"
            try:
                stream_url = self._publisher.start(stream_path)
                self._state.is_running = True
                self._state.session_id = session_id
                self._state.camera_id = camera_id or self._config.camera_id
                self._state.stream_url = stream_url
                self._state.last_started_at = datetime.now(timezone.utc).isoformat()
                self._state.last_error = None
                self._ensure_heartbeat()
                return {
                    "status": "started",
                    "streamUrl": stream_url,
                    "cameraId": self._state.camera_id,
                    "sessionId": session_id,
                }
            except Exception as exc:
                self._state.last_error = str(exc)
                raise

    def stop(self, session_id: int) -> dict:
        with self._lock:
            if self._state.session_id not in (None, session_id):
                raise RuntimeError(
                    f"Cannot stop session {session_id}; active session is {self._state.session_id}"
                )

            self._publisher.stop()
            self._state.is_running = False
            self._state.session_id = None
            self._state.stream_url = None
            self._heartbeat_stop.set()
            return {"status": "stopped", "sessionId": session_id}

    def status(self) -> dict:
        with self._lock:
            return {
                "status": "running" if self._state.is_running else "idle",
                "is_running": self._state.is_running,
                "sessionId": self._state.session_id,
                "cameraId": self._state.camera_id,
                "streamUrl": self._state.stream_url,
                "fps": self._state.fps,
                "lastError": self._state.last_error,
                "lastStartedAt": self._state.last_started_at,
            }

    def shutdown(self) -> None:
        self._heartbeat_stop.set()
        self._publisher.stop_all()

    def _ensure_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._heartbeat_stop.clear()
        self._heartbeat_thread = Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self._config.heartbeat_interval_seconds):
            try:
                snapshot = self.status()
                self._backend_client.send_heartbeat(
                    {
                        "deviceCode": self._config.device_code,
                        "status": "online" if snapshot["is_running"] or not snapshot["lastError"] else "error",
                        "activeSessionId": snapshot["sessionId"],
                        "streamUrl": snapshot["streamUrl"],
                        "metadata": {
                            "lastError": snapshot["lastError"],
                            "fps": snapshot["fps"],
                        },
                    }
                )
            except Exception as exc:
                logger.warning("Failed to send heartbeat: %s", exc)
