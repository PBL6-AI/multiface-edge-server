from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from typing import Optional

from .backend_client import BackendClient
from .config import EdgeServerConfig
from .rtsp_publisher import RtspPublisher
from .video_recorder import VideoRecorder

logger = logging.getLogger(__name__)


@dataclass
class EdgeRuntimeState:
    registration_succeeded: bool = False
    is_running: bool = False
    session_id: Optional[int] = None
    camera_id: Optional[str] = None
    stream_url: Optional[str] = None
    fps: Optional[int] = None
    status: str = "idle"
    last_error: Optional[str] = None
    last_started_at: Optional[str] = None
    is_recording: bool = False
    recording_id: Optional[str] = None
    recording_file_path: Optional[str] = None
    recording_source: Optional[str] = None
    recording_started_at: Optional[str] = None
    preview_stream_path: Optional[str] = None
    preview_url: Optional[str] = None


class CameraEdgeService:
    def __init__(self, config: EdgeServerConfig, backend_client: BackendClient) -> None:
        self._config = config
        self._backend_client = backend_client
        self._publisher = RtspPublisher(config)
        self._recorder = VideoRecorder(config)
        self._lock = RLock()
        self._heartbeat_stop = Event()
        self._heartbeat_thread: Optional[Thread] = None
        self._state = EdgeRuntimeState(
            camera_id=config.camera_id,
            fps=config.target_fps,
        )

    def preflight_check(self) -> dict:
        logger.info("Running edge preflight checks...")
        self._backend_client.check_connectivity()
        publisher_info = self._publisher.preflight_check()
        logger.info("Edge preflight checks completed successfully.")
        return {
            "backendUrl": self._config.backend_url,
            **publisher_info,
        }

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
                "cameraBinary": self._publisher.camera_binary
                or self._config.camera_probe_binary
                or self._config.rpicam_binary
                or self._config.libcamera_binary,
                "webrtcBaseUrl": self._config.webrtc_base_url,
            },
        }
        self._backend_client.register_device(payload)
        with self._lock:
            self._state.registration_succeeded = True
            self._state.status = "online"
            self._state.last_error = None
        self._ensure_heartbeat()
        self._send_heartbeat(mode="register")

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
                self._state.status = "running"
                self._state.last_started_at = datetime.now(timezone.utc).isoformat()
                self._state.last_error = None
                self._ensure_heartbeat()
                self._send_heartbeat(mode="running")
                return {
                    "status": "started",
                    "streamUrl": stream_url,
                    "cameraId": self._state.camera_id,
                    "sessionId": session_id,
                }
            except Exception as exc:
                self._state.last_error = str(exc)
                self._state.status = "error"
                raise

    def start_preview(self, stream_path: str | None = None) -> dict:
        with self._lock:
            if self._state.is_running and self._state.session_id is not None:
                raise RuntimeError(
                    f"Edge device is already running attendance session {self._state.session_id}"
                )

            resolved_path = (
                stream_path
                or f"{self._config.device_code}/enrollment-preview"
            ).strip("/")
            try:
                stream_url = self._publisher.start(resolved_path)
                self._state.is_running = True
                self._state.session_id = None
                self._state.camera_id = self._config.camera_id
                self._state.stream_url = stream_url
                self._state.preview_stream_path = resolved_path
                self._state.preview_url = self._build_preview_url(resolved_path)
                self._state.status = "previewing"
                self._state.last_started_at = datetime.now(timezone.utc).isoformat()
                self._state.last_error = None
                self._ensure_heartbeat()
                self._send_heartbeat(mode="previewing")
                return {
                    "status": "started",
                    "streamUrl": stream_url,
                    "previewUrl": self._state.preview_url,
                    "streamPath": resolved_path,
                    "cameraId": self._state.camera_id,
                }
            except Exception as exc:
                self._state.last_error = str(exc)
                self._state.status = "error"
                raise

    def stop_preview(self) -> dict:
        with self._lock:
            if self._state.session_id is not None:
                raise RuntimeError(
                    f"Cannot stop preview while attendance session {self._state.session_id} is running"
                )

            self._publisher.stop()
            self._state.is_running = False
            self._state.stream_url = None
            self._state.preview_stream_path = None
            self._state.preview_url = None
            self._state.status = (
                "online" if self._state.registration_succeeded else "idle"
            )
            self._state.last_error = None
            self._ensure_heartbeat()
            self._send_heartbeat(mode="preview_stopped")
            return {"status": "stopped"}

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
            self._state.status = (
                "online" if self._state.registration_succeeded else "idle"
            )
            self._state.last_error = None
            self._ensure_heartbeat()
            self._send_heartbeat(mode="idle")
            return {"status": "stopped", "sessionId": session_id}

    def status(self) -> dict:
        with self._lock:
            return {
                "status": self._state.status,
                "is_running": self._state.is_running,
                "sessionId": self._state.session_id,
                "cameraId": self._state.camera_id,
                "streamUrl": self._state.stream_url,
                "previewUrl": self._state.preview_url,
                "previewStreamPath": self._state.preview_stream_path,
                "fps": self._state.fps,
                "lastError": self._state.last_error,
                "lastStartedAt": self._state.last_started_at,
                "recording": self.recording_status(),
            }

    def start_recording(
        self,
        recording_id: str | None = None,
        file_name: str | None = None,
    ) -> dict:
        with self._lock:
            try:
                source_url = self._state.stream_url if self._state.is_running else None
                result = self._recorder.start(
                    recording_id=recording_id,
                    source_url=source_url,
                    file_name=file_name,
                )
                self._state.is_recording = result["isRecording"]
                self._state.recording_id = result["recordingId"]
                self._state.recording_file_path = result["filePath"]
                self._state.recording_source = result["source"]
                self._state.recording_started_at = result["startedAt"]
                self._state.last_error = None
                if not self._state.is_running:
                    self._state.status = "recording"
                self._ensure_heartbeat()
                self._send_heartbeat(mode="recording")
                return result
            except Exception as exc:
                self._state.last_error = str(exc)
                self._state.status = "error"
                raise

    def stop_recording(self, recording_id: str | None = None) -> dict:
        with self._lock:
            result = self._recorder.stop(recording_id=recording_id)
            self._state.is_recording = False
            self._state.recording_id = None
            self._state.recording_file_path = None
            self._state.recording_source = None
            self._state.recording_started_at = None
            self._state.status = (
                "running"
                if self._state.is_running
                else "online"
                if self._state.registration_succeeded
                else "idle"
            )
            self._state.last_error = None
            self._ensure_heartbeat()
            self._send_heartbeat(mode="recording_stopped")
            return result

    def recording_status(self) -> dict:
        recorder_status = self._recorder.status()
        return {
            **recorder_status,
            "recordingId": self._state.recording_id or recorder_status["recordingId"],
            "filePath": self._state.recording_file_path or recorder_status["filePath"],
            "source": self._state.recording_source or recorder_status["source"],
            "startedAt": self._state.recording_started_at
            or recorder_status["startedAt"],
        }

    def shutdown(self) -> None:
        self._heartbeat_stop.set()
        self._recorder.stop()
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
                self._send_heartbeat(mode="periodic")
            except Exception as exc:
                with self._lock:
                    self._state.last_error = str(exc)
                    self._state.status = "error"
                logger.warning("Failed to send heartbeat: %s", exc)

    def _send_heartbeat(self, mode: str) -> None:
        snapshot = self.status()
        heartbeat_status = "running" if snapshot["is_running"] else "online"
        self._backend_client.send_heartbeat(
            {
                "deviceCode": self._config.device_code,
                "status": heartbeat_status,
                "activeSessionId": snapshot["sessionId"],
                "streamUrl": snapshot["streamUrl"],
                "metadata": {
                    "mode": mode,
                    "lastError": snapshot["lastError"],
                    "fps": snapshot["fps"],
                    "recording": snapshot["recording"],
                    "previewUrl": snapshot["previewUrl"],
                    "cameraBinary": self._publisher.camera_binary
                    or self._recorder.camera_binary
                    or self._config.camera_probe_binary
                    or self._config.rpicam_binary
                    or self._config.libcamera_binary,
                },
            }
        )
        with self._lock:
            self._state.status = (
                "running"
                if self._state.is_running
                else "recording"
                if self._state.is_recording
                else "online"
            )
            self._state.last_error = None

    def _build_preview_url(self, stream_path: str) -> Optional[str]:
        if not self._config.webrtc_base_url:
            return None
        return f"{self._config.webrtc_base_url.rstrip('/')}/{stream_path.strip('/')}/"
