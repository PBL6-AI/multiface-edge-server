from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional

from .config import EdgeServerConfig

logger = logging.getLogger(__name__)


@dataclass
class PublisherRuntime:
    mediamtx_process: Optional[subprocess.Popen] = None
    publisher_process: Optional[subprocess.Popen] = None
    stream_url: Optional[str] = None


class RtspPublisher:
    def __init__(self, config: EdgeServerConfig) -> None:
        self._config = config
        self._runtime = PublisherRuntime()

    @property
    def stream_url(self) -> Optional[str]:
        return self._runtime.stream_url

    def start(self, stream_path: str) -> str:
        if self._runtime.publisher_process and self._runtime.publisher_process.poll() is None:
            return self._runtime.stream_url or self._build_stream_url(stream_path)

        self._start_mediamtx_if_needed()
        stream_url = self._build_stream_url(stream_path)
        command = self._build_publish_command(stream_url)
        logger.info("Starting RTSP publisher: %s", command)
        self._runtime.publisher_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
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
        if self._runtime.mediamtx_process and self._runtime.mediamtx_process.poll() is None:
            return

        command = [self._config.mediamtx_binary]
        if self._config.mediamtx_config:
            command.append(self._config.mediamtx_config)

        logger.info("Starting mediamtx: %s", shlex.join(command))
        self._runtime.mediamtx_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

    def _build_stream_url(self, stream_path: str) -> str:
        return f"{self._config.stream_base_url.rstrip('/')}/{stream_path}"

    def _build_publish_command(self, stream_url: str) -> list[str]:
        libcamera = [
            self._config.libcamera_binary,
            "--inline",
            "--nopreview",
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
            self._config.ffmpeg_binary,
            "-re",
            "-i",
            "-",
            "-an",
            "-c:v",
            "copy",
            "-f",
            "rtsp",
            stream_url,
        ]

        return [
            "/bin/bash",
            "-lc",
            f"{shlex.join(libcamera)} | {shlex.join(ffmpeg)}",
        ]

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
