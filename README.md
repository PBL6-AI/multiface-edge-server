# Flask Edge Server for Raspberry Pi

## Purpose

This Flask server is the Raspberry Pi edge orchestrator for attendance v1.

It does **not** run face recognition inference.

Responsibilities:

- open ArduCam IMX519 through `libcamera-vid`
- publish RTSP through `mediamtx`
- expose control endpoints for backend
- send heartbeat to backend

## Files

- [edge_server/app.py](/D:/H-Coding/PBL5/multiface-attendace-for-classroom/edge_server/app.py)
- [edge_server/camera_service.py](/D:/H-Coding/PBL5/multiface-attendace-for-classroom/edge_server/camera_service.py)
- [edge_server/rtsp_publisher.py](/D:/H-Coding/PBL5/multiface-attendace-for-classroom/edge_server/rtsp_publisher.py)
- [edge_server/backend_client.py](/D:/H-Coding/PBL5/multiface-attendace-for-classroom/edge_server/backend_client.py)
- [run_edge_server.py](/D:/H-Coding/PBL5/multiface-attendace-for-classroom/run_edge_server.py)

## Install

```bash
pip install -r requirements-edge.txt
```

## Environment

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
FFMPEG_BINARY=ffmpeg
FRAME_WIDTH=1280
FRAME_HEIGHT=720
TARGET_FPS=15
HEARTBEAT_INTERVAL_SECONDS=15
```

## Run

```bash
python run_edge_server.py
```

## Endpoints

- `GET /health`
- `POST /attendance/start`
- `POST /attendance/stop`
- `GET /attendance/status`

## Example start request

```json
{
  "sessionId": 91,
  "sourceDeviceId": "pi-room-a-01",
  "cameraId": "cam-imx519-01"
}
```

## Example response

```json
{
  "status": "started",
  "streamUrl": "rtsp://192.168.1.50:8554/pi-room-a-01/session-91",
  "cameraId": "cam-imx519-01",
  "sessionId": 91
}
```
