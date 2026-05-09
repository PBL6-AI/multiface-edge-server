from dataclasses import dataclass
import os


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
    default_stream_path: str = os.getenv("DEFAULT_STREAM_PATH", "attendance")
    mediamtx_binary: str = os.getenv("MEDIAMTX_BINARY", "mediamtx")
    mediamtx_config: str = os.getenv("MEDIAMTX_CONFIG", "")
    libcamera_binary: str = os.getenv("LIBCAMERA_BINARY", "libcamera-vid")
    ffmpeg_binary: str = os.getenv("FFMPEG_BINARY", "ffmpeg")
    frame_width: int = int(os.getenv("FRAME_WIDTH", "1280"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "720"))
    target_fps: int = int(os.getenv("TARGET_FPS", "15"))
    heartbeat_interval_seconds: int = int(
        os.getenv("HEARTBEAT_INTERVAL_SECONDS", "15")
    )
