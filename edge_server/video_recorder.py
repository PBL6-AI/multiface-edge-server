from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import EdgeServerConfig

logger = logging.getLogger(__name__)


@dataclass
class RecorderRuntime:
    process: Optional[subprocess.Popen] = None
    recording_id: Optional[str] = None
    file_path: Optional[str] = None
    source: Optional[str] = None
    camera_binary: Optional[str] = None
    started_at: Optional[str] = None


class VideoRecorder:
    def __init__(self, config: EdgeServerConfig) -> None:
        self._config = config
        self._runtime = RecorderRuntime()

    @property
    def is_recording(self) -> bool:
        return bool(self._runtime.process and self._runtime.process.poll() is None)

    @property
    def camera_binary(self) -> Optional[str]:
        return self._runtime.camera_binary

    def start(
        self,
        recording_id: str | None = None,
        source_url: str | None = None,
        file_name: str | None = None,
    ) -> dict:
        if self.is_recording:
            return self.status()

        output_path = self._build_output_path(recording_id, file_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = (
            self._build_rtsp_record_command(source_url, output_path)
            if source_url
            else self._build_camera_record_command(output_path)
        )

        logger.info("Starting video recorder command: %s", shlex.join(command))
        popen_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "shell": False,
        }
        if os.name == "posix":
            popen_kwargs["preexec_fn"] = os.setsid

        self._runtime.process = subprocess.Popen(command, **popen_kwargs)
        time.sleep(self._config.process_start_grace_seconds)
        if self._runtime.process.poll() is not None:
            stdout, stderr = self._runtime.process.communicate(timeout=1)
            self._runtime = RecorderRuntime()
            raise RuntimeError(
                "Video recorder exited during startup"
                f" | stdout={stdout.strip()[:500]} | stderr={stderr.strip()[:500]}"
            )

        started_at = datetime.now(timezone.utc).isoformat()
        self._runtime.recording_id = output_path.stem
        self._runtime.file_path = str(output_path)
        self._runtime.source = source_url or "camera"
        self._runtime.started_at = started_at
        return self.status()

    def stop(self, recording_id: str | None = None) -> dict:
        if recording_id and self._runtime.recording_id not in (None, recording_id):
            raise RuntimeError(
                f"Cannot stop recording {recording_id}; active recording is {self._runtime.recording_id}"
            )

        active_snapshot = self.status()
        self._terminate_process(self._runtime.process)
        stopped_at = datetime.now(timezone.utc).isoformat()
        result = {
            **active_snapshot,
            "isRecording": False,
            "status": "stopped",
            "stoppedAt": stopped_at,
        }
        self._runtime = RecorderRuntime()
        return result

    def status(self) -> dict:
        return {
            "status": "recording" if self.is_recording else "idle",
            "isRecording": self.is_recording,
            "recordingId": self._runtime.recording_id,
            "filePath": self._runtime.file_path,
            "source": self._runtime.source,
            "startedAt": self._runtime.started_at,
        }

    def _build_output_path(
        self, recording_id: str | None, file_name: str | None
    ) -> Path:
        if file_name:
            safe_name = self._sanitize_file_name(file_name)
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            base = recording_id or f"{self._config.device_code}-{timestamp}"
            safe_name = self._sanitize_file_name(base)

        if not safe_name.endswith(".mp4"):
            safe_name = f"{safe_name}.mp4"

        return Path(self._config.recordings_dir).expanduser().resolve() / safe_name

    def _build_rtsp_record_command(self, source_url: str, output_path: Path) -> list[str]:
        return [
            self._resolve_binary(self._config.ffmpeg_binary),
            "-y",
            "-rtsp_transport",
            "tcp",
            "-i",
            source_url,
            "-an",
            "-c:v",
            "copy",
            str(output_path),
        ]

    def _build_camera_record_command(self, output_path: Path) -> list[str]:
        camera_binary = self._resolve_camera_video_binary()
        self._runtime.camera_binary = camera_binary
        camera_cmd = [
            camera_binary,
            "--inline",
            "--nopreview",
            "--timeout",
            "0",
            "--width",
            str(self._config.frame_width),
            "--height",
            str(self._config.frame_height),
            "--framerate",
            str(self._config.target_fps),
            "--codec",
            "h264",
            "-o",
            "-",
        ]

        ffmpeg = [
            self._resolve_binary(self._config.ffmpeg_binary),
            "-y",
            "-f",
            "h264",
            "-i",
            "-",
            "-an",
            "-c:v",
            "copy",
            str(output_path),
        ]

        return [
            "/bin/bash",
            "-lc",
            f"{shlex.join(camera_cmd)} | {shlex.join(ffmpeg)}",
        ]

    def _resolve_camera_video_binary(self) -> str:
        candidates = [self._config.libcamera_binary, self._config.rpicam_binary]
        return self._resolve_first_available(candidates, "camera video recorder")

    @staticmethod
    def _resolve_binary(binary: str) -> str:
        resolved = shutil.which(binary)
        if resolved:
            return resolved
        raise FileNotFoundError(f"Required binary not found in PATH: {binary}")

    def _resolve_first_available(self, candidates: list[str], label: str) -> str:
        for candidate in candidates:
            if not candidate:
                continue
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        raise FileNotFoundError(
            f"Unable to find a valid {label} binary. Tried: {', '.join(candidates)}"
        )

    @staticmethod
    def _sanitize_file_name(value: str) -> str:
        value = Path(value).name.strip()
        value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value)
        return value.strip(".-") or "recording"

    @staticmethod
    def _terminate_process(process: Optional[subprocess.Popen]) -> None:
        if process is None or process.poll() is not None:
            return

        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
        else:
            process.terminate()

        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
