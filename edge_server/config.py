import os
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


def _derive_webrtc_base_url(stream_base_url: str) -> str:
    explicit = os.getenv("WEBRTC_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")

    parsed = urlparse(stream_base_url)
    if not parsed.hostname:
        return ""

    return urlunparse(("http", f"{parsed.hostname}:8889", "", "", "", "")).rstrip("/")


@dataclass
class EdgeServerConfig:
    backend_url: str = os.getenv("BACKEND_URL", "http://localhost:3000")
    edge_token: str = os.getenv("BACKEND_EDGE_TOKEN", "")
    device_code: str = os.getenv("DEVICE_CODE", "pi-room-a-01")
    device_name: str = os.getenv("DEVICE_NAME", "Raspberry Pi Room A")
    room_code: str = os.getenv("ROOM_CODE", "A101")
    camera_id: str = os.getenv("CAMERA_ID", "cam-imx519-01")
    control_base_url: str = os.getenv("CONTROL_BASE_URL", "http://localhost:5000")
    stream_base_url: str = os.getenv("STREAM_BASE_URL", "rtsp://localhost:8554")
    webrtc_base_url: str = _derive_webrtc_base_url(stream_base_url)
    default_stream_path: str = os.getenv("DEFAULT_STREAM_PATH", "attendance")
    recordings_dir: str = os.getenv("RECORDINGS_DIR", "recordings")
    mediamtx_binary: str = os.getenv("MEDIAMTX_BINARY", "mediamtx")
    mediamtx_config: str = os.getenv("MEDIAMTX_CONFIG", "")
    libcamera_binary: str = os.getenv("LIBCAMERA_BINARY", "libcamera-vid")
    rpicam_binary: str = os.getenv("RPICAM_BINARY", "rpicam-vid")
    camera_probe_binary: str = os.getenv("CAMERA_PROBE_BINARY", "")
    ffmpeg_binary: str = os.getenv("FFMPEG_BINARY", "ffmpeg")
    frame_width: int = int(os.getenv("FRAME_WIDTH", "1280"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "720"))
    target_fps: int = int(os.getenv("TARGET_FPS", "15"))
    startup_probe_timeout_seconds: int = int(
        os.getenv("STARTUP_PROBE_TIMEOUT_SECONDS", "5")
    )
    process_start_grace_seconds: float = float(
        os.getenv("PROCESS_START_GRACE_SECONDS", "2")
    )
    port: int = int(os.getenv("PORT", "5000"))
    heartbeat_interval_seconds: int = int(
        os.getenv("HEARTBEAT_INTERVAL_SECONDS", "15")
    )
    backend_retry_attempts: int = int(os.getenv("BACKEND_RETRY_ATTEMPTS", "5"))
    backend_retry_delay_seconds: float = float(
        os.getenv("BACKEND_RETRY_DELAY_SECONDS", "2")
    )
