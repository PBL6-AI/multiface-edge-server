from __future__ import annotations

import logging
import os
import signal
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
        if not self._start_publisher(stream_url, camera_binary, low_latency=True):
            logger.warning(
                "Low-latency RTSP publisher failed during startup; retrying with "
                "the stable publisher command."
            )
            if not self._start_publisher(stream_url, camera_binary, low_latency=False):
                raise RuntimeError("RTSP publisher exited during startup")

        self._runtime.stream_url = stream_url
        return stream_url

    def stop(self) -> None:
        self._terminate_process(self._runtime.publisher_process, process_group=True)
        self._runtime.publisher_process = None
        self._runtime.stream_url = None
        time.sleep(0.5)

    def stop_all(self) -> None:
        self.stop()
        self._terminate_process(self._runtime.mediamtx_process, process_group=True)
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
            start_new_session=True,
        )
        time.sleep(self._config.process_start_grace_seconds)
        if self._runtime.mediamtx_process.poll() is not None:
            process = self._runtime.mediamtx_process
            stdout, stderr = process.communicate(timeout=1)
            self._terminate_process(process, process_group=True)
            self._runtime.mediamtx_process = None
            combined_output = f"{stdout}\n{stderr}".lower()
            if "address already in use" in combined_output:
                logger.warning(
                    "mediamtx port is already in use; assuming an existing MediaMTX "
                    "instance will serve the RTSP stream."
                )
                return
            raise RuntimeError(
                "mediamtx exited during startup"
                f" | stdout={stdout.strip()[:500]} | stderr={stderr.strip()[:500]}"
            )

    def _build_stream_url(self, stream_path: str) -> str:
        return f"{self._config.stream_base_url.rstrip('/')}/{stream_path}"

    def _start_publisher(
        self,
        stream_url: str,
        camera_binary: str,
        low_latency: bool,
    ) -> bool:
        command = self._build_publish_command(
            stream_url,
            camera_binary,
            low_latency=low_latency,
        )
        mode = "low-latency" if low_latency else "stable"
        logger.info("Starting %s RTSP publisher command: %s", mode, shlex.join(command))
        self._runtime.publisher_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            start_new_session=True,
        )
        time.sleep(self._config.process_start_grace_seconds)
        if self._runtime.publisher_process.poll() is None:
            return True

        process = self._runtime.publisher_process
        stdout, stderr = process.communicate(timeout=1)
        self._terminate_process(process, process_group=True)
        self._runtime.publisher_process = None
        logger.error(
            "%s RTSP publisher exited during startup | stdout=%s | stderr=%s",
            mode,
            stdout.strip()[:2000],
            stderr.strip()[:4000],
        )
        return False

    def _build_publish_command(
        self,
        stream_url: str,
        camera_binary: str,
        low_latency: bool = True,
    ) -> list[str]:
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
        if low_latency:
            camera_cmd[-2:-2] = ["--intra", str(self._config.target_fps)]

        ffmpeg = [self._resolve_binary(self._config.ffmpeg_binary)]
        if low_latency:
            ffmpeg.extend(
                [
                    "-fflags",
                    "nobuffer",
                    "-flags",
                    "low_delay",
                    "-probesize",
                    "32",
                    "-analyzeduration",
                    "0",
                ]
            )
        else:
            ffmpeg.append("-re")

        ffmpeg.extend(["-i", "-", "-an", "-c:v", "copy"])
        if low_latency:
            ffmpeg.extend(["-flush_packets", "1"])
        ffmpeg.extend(["-f", "rtsp", "-rtsp_transport", "tcp"])
        if low_latency:
            ffmpeg.extend(["-muxdelay", "0", "-muxpreload", "0"])
        ffmpeg.append(stream_url)

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
    def _terminate_process(
        process: Optional[subprocess.Popen],
        process_group: bool = False,
    ) -> None:
        if process is None:
            return

        if process_group and os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as exc:
                logger.warning("Failed to terminate process group %s: %s", process.pid, exc)
        elif process.poll() is None:
            process.terminate()

        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass

        if process_group and os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as exc:
                logger.warning("Failed to kill process group %s: %s", process.pid, exc)
        else:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("Process %s did not exit after kill.", process.pid)
