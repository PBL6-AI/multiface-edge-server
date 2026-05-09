from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from .config import EdgeServerConfig

logger = logging.getLogger(__name__)


@dataclass
class PublisherRuntime:
    mediamtx_process: Optional[subprocess.Popen] = None
    publisher_process: Optional[subprocess.Popen] = None
    stream_url: Optional[str] = None
    camera_binary: Optional[str] = None


class RtspPublisher:
    def __init__(self, config: EdgeServerConfig) -> None:
        self._config = config
        self._runtime = PublisherRuntime()

    @property
    def stream_url(self) -> Optional[str]:
        return self._runtime.stream_url

    @property
    def camera_binary(self) -> Optional[str]:
        return self._runtime.camera_binary

    def preflight_check(self) -> dict[str, str]:
        mediamtx_binary = self._resolve_binary(self._config.mediamtx_binary)
        ffmpeg_binary = self._resolve_binary(self._config.ffmpeg_binary)
        camera_binary = self._resolve_camera_video_binary()
        probe_binary = self._resolve_camera_probe_binary(camera_binary)
        self._probe_camera(probe_binary)
        self._runtime.camera_binary = camera_binary
        return {
            "cameraBinary": camera_binary,
            "cameraProbeBinary": probe_binary,
            "ffmpegBinary": ffmpeg_binary,
            "mediamtxBinary": mediamtx_binary,
        }

    def start(self, stream_path: str) -> str:
        if (
            self._runtime.publisher_process
            and self._runtime.publisher_process.poll() is None
        ):
            return self._runtime.stream_url or self._build_stream_url(stream_path)

        camera_binary = self._resolve_camera_video_binary()
        self._runtime.camera_binary = camera_binary
        self._start_mediamtx_if_needed()
        stream_url = self._build_stream_url(stream_path)
        command = self._build_publish_command(stream_url, camera_binary)
        logger.info("Starting RTSP publisher command: %s", shlex.join(command))
        self._runtime.publisher_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        time.sleep(self._config.process_start_grace_seconds)
        if self._runtime.publisher_process.poll() is not None:
            stdout, stderr = self._runtime.publisher_process.communicate(timeout=1)
            self._runtime.publisher_process = None
            raise RuntimeError(
                "RTSP publisher exited during startup"
                f" | stdout={stdout.strip()[:500]} | stderr={stderr.strip()[:500]}"
            )
        self._runtime.stream_url = stream_url
        return stream_url

    def stop(self) -> None:
        self._terminate_process(self._runtime.publisher_process)
        self._runtime.publisher_process = None
        self._runtime.stream_url = None

    def stop_all(self) -> None:
        self.stop()
        self._terminate_process(self._runtime.mediamtx_process)
        self._runtime.mediamtx_process = None

    def _start_mediamtx_if_needed(self) -> None:
        if (
            self._runtime.mediamtx_process
            and self._runtime.mediamtx_process.poll() is None
        ):
            return

        mediamtx_binary = self._resolve_binary(self._config.mediamtx_binary)
        command = [mediamtx_binary]
        if self._config.mediamtx_config:
            command.append(self._config.mediamtx_config)

        logger.info("Starting mediamtx: %s", shlex.join(command))
        self._runtime.mediamtx_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        time.sleep(self._config.process_start_grace_seconds)
        if self._runtime.mediamtx_process.poll() is not None:
            stdout, stderr = self._runtime.mediamtx_process.communicate(timeout=1)
            self._runtime.mediamtx_process = None
            raise RuntimeError(
                "mediamtx exited during startup"
                f" | stdout={stdout.strip()[:500]} | stderr={stderr.strip()[:500]}"
            )

    def _build_stream_url(self, stream_path: str) -> str:
        return f"{self._config.stream_base_url.rstrip('/')}/{stream_path}"

    def _build_publish_command(self, stream_url: str, camera_binary: str) -> list[str]:
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
            "-re",
            "-i",
            "-",
            "-an",
            "-c:v",
            "copy",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            stream_url,
        ]

        return [
            "/bin/bash",
            "-lc",
            f"{shlex.join(camera_cmd)} | {shlex.join(ffmpeg)}",
        ]

    def _resolve_camera_video_binary(self) -> str:
        candidates = [self._config.libcamera_binary, self._config.rpicam_binary]
        return self._resolve_first_available(candidates, "camera video publisher")

    def _resolve_camera_probe_binary(self, camera_binary: str) -> str:
        explicit = self._config.camera_probe_binary.strip()
        if explicit:
            return self._resolve_binary(explicit)

        derived_candidates = []
        if camera_binary.endswith("-vid"):
            derived_candidates.append(camera_binary[:-4] + "-still")
        derived_candidates.extend(["rpicam-still", "libcamera-still"])
        return self._resolve_first_available(derived_candidates, "camera probe")

    def _probe_camera(self, probe_binary: str) -> None:
        logger.info("Checking camera availability with: %s --list-cameras", probe_binary)
        result = subprocess.run(
            [probe_binary, "--list-cameras"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self._config.startup_probe_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Camera probe failed"
                f" | stdout={result.stdout.strip()[:500]} | stderr={result.stderr.strip()[:500]}"
            )

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
    def _terminate_process(process: Optional[subprocess.Popen]) -> None:
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
