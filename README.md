# Flask Edge Server for Raspberry Pi

## Purpose

This Flask server is the Raspberry Pi edge orchestrator for attendance v1.

It does **not** run face recognition inference.

Responsibilities:

- open ArduCam or Raspberry Pi camera through `libcamera-vid` or `rpicam-vid`
- publish RTSP through `mediamtx`
- expose control endpoints for backend
- register itself and keep heartbeat alive, even while idle

## Runtime behavior

On startup the service now:

1. checks backend reachability
2. verifies required binaries exist
3. probes the camera with `rpicam-still --list-cameras` or `libcamera-still --list-cameras`
4. registers the edge device to backend
5. sends heartbeat immediately and continues heartbeat while idle

This makes the backend see the Pi as `online` before the teacher starts an attendance session.

## Key files

- [edge_server/app.py](/D:/H-Coding/PBL5/multiface-edge-server/edge_server/app.py)
- [edge_server/camera_service.py](/D:/H-Coding/PBL5/multiface-edge-server/edge_server/camera_service.py)
- [edge_server/rtsp_publisher.py](/D:/H-Coding/PBL5/multiface-edge-server/edge_server/rtsp_publisher.py)
- [edge_server/backend_client.py](/D:/H-Coding/PBL5/multiface-edge-server/edge_server/backend_client.py)
- [run_edge_server.py](/D:/H-Coding/PBL5/multiface-edge-server/run_edge_server.py)
- [deploy/raspberry-pi/README.md](/D:/H-Coding/PBL5/multiface-edge-server/deploy/raspberry-pi/README.md)

## Python install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

Start from `.env.example`.

```env
BACKEND_URL=http://backend-server:3000
BACKEND_EDGE_TOKEN=test-internal-token
DEVICE_CODE=pi-room-a-01
DEVICE_NAME=Raspberry Pi Room A
ROOM_CODE=A101
CAMERA_ID=cam-imx519-01
CONTROL_BASE_URL=http://192.168.1.50:5000
STREAM_BASE_URL=rtsp://192.168.1.50:8554
DEFAULT_STREAM_PATH=attendance
MEDIAMTX_BINARY=mediamtx
MEDIAMTX_CONFIG=
LIBCAMERA_BINARY=libcamera-vid
RPICAM_BINARY=rpicam-vid
CAMERA_PROBE_BINARY=
FFMPEG_BINARY=ffmpeg
FRAME_WIDTH=1280
FRAME_HEIGHT=720
TARGET_FPS=15
STARTUP_PROBE_TIMEOUT_SECONDS=5
PROCESS_START_GRACE_SECONDS=2
PORT=5000
HEARTBEAT_INTERVAL_SECONDS=15
BACKEND_RETRY_ATTEMPTS=5
BACKEND_RETRY_DELAY_SECONDS=2
```

Notes:

- `CONTROL_BASE_URL` must be the HTTP URL the backend can call on the Pi.
- `STREAM_BASE_URL` must be the RTSP URL the AI service can pull from.
- Leave `CAMERA_PROBE_BINARY` empty unless your Pi uses a non-standard camera probe command.

## Run manually

```bash
python run_edge_server.py
```

If startup passes, the logs will print the preflight result and the device will register itself immediately.

## Endpoints

- `GET /health`
- `POST /attendance/start`
- `POST /attendance/stop`
- `GET /attendance/status`

`GET /attendance/status` returns:

```json
{
  "status": "online",
  "is_running": false,
  "sessionId": null,
  "cameraId": "cam-imx519-01",
  "streamUrl": null,
  "fps": 15,
  "lastError": null,
  "lastStartedAt": null
}
```

## Debug checklist

- Check health locally on the Pi:
  - `curl http://localhost:5000/health`
- Check service logs:
  - `journalctl -u multiface-edge -f`
- Check camera:
  - `rpicam-still --list-cameras`
  - `libcamera-still --list-cameras`
- Check manual start from laptop on the same LAN:
  - `curl -X POST http://<pi-ip>:5000/attendance/start -H "content-type: application/json" -d '{"sessionId":91,"cameraId":"cam-imx519-01"}'`

## Raspberry Pi deployment

Use the runbook here:

- [deploy/raspberry-pi/README.md](/D:/H-Coding/PBL5/multiface-edge-server/deploy/raspberry-pi/README.md)
- [deploy/raspberry-pi/multiface-edge.service](/D:/H-Coding/PBL5/multiface-edge-server/deploy/raspberry-pi/multiface-edge.service)
