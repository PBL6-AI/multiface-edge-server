# Flask Edge Server for Raspberry Pi

## Purpose

This Flask server is the Raspberry Pi edge orchestrator for attendance v1.

It does **not** run face recognition inference.

Responsibilities:

- open ArduCam or Raspberry Pi camera through `libcamera-vid` or `rpicam-vid`
- publish RTSP through `mediamtx`
- record camera/RTSP video to local files for later sync or download
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
- [edge_server/video_recorder.py](/D:/H-Coding/PBL5/multiface-edge-server/edge_server/video_recorder.py)
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
RECORDINGS_DIR=recordings
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
- `RECORDINGS_DIR` is where `.mp4` recordings are written on the machine running this server. Use a mounted laptop/shared folder if the Pi must write directly to laptop storage.
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
- `POST /recording/start`
- `POST /recording/stop`
- `POST /recording/end`
- `GET /recording/status`
- `GET /recording/files/<file_name>`

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
  "lastStartedAt": null,
  "recording": {
    "status": "idle",
    "isRecording": false,
    "recordingId": null,
    "filePath": null,
    "source": null,
    "startedAt": null
  }
}
```

Recording can run in two modes:

- If attendance streaming is already running, recording pulls from the active RTSP stream.
- If no attendance stream is running, recording opens the camera directly.

Start recording:

```bash
curl -X POST http://<pi-ip>:5000/recording/start \
  -H "content-type: application/json" \
  -d '{"sessionId":91}'
```

Stop recording:

```bash
curl -X POST http://<pi-ip>:5000/recording/end \
  -H "content-type: application/json" \
  -d '{"recordingId":"session-91"}'
```

Download the saved file to the laptop:

```bash
curl -o session-91.mp4 http://<pi-ip>:5000/recording/files/session-91.mp4
```

## Recording runbook

Mục này mô tả flow dùng Raspberry Pi để mở camera, ghi video, rồi tải file video về laptop.

### 1. Xác định IP của Raspberry Pi

SSH vào Pi rồi chạy:

```bash
hostname -I
```

Ví dụ kết quả:

```bash
192.168.1.50 172.17.0.1
```

Trong các lệnh gọi từ laptop/backend, thay `<pi-ip>` bằng IP của Pi, ví dụ `192.168.1.50`.

Nếu đang gọi lệnh ngay trong SSH terminal của Pi, có thể dùng `localhost`:

```bash
curl http://localhost:5000/health
```

Nếu gọi từ laptop, dùng IP của Pi:

```bash
curl http://192.168.1.50:5000/health
```

### 2. Chạy edge server trên Pi

Trên Pi:

```bash
cd ~/apps/multiface-edge-server
source .venv/bin/activate
python run_edge_server.py
```

Nếu virtual environment của bạn tên là `venv` thay vì `.venv`, dùng:

```bash
source venv/bin/activate
```

Khi server chạy thành công, service sẽ listen ở port `5000`.

### 3. Start camera stream cho attendance

Chạy trên Pi:

```bash
curl -X POST http://localhost:5000/attendance/start \
  -H "content-type: application/json" \
  -d '{"sessionId":91,"cameraId":"cam-imx519-01"}'
```

Hoặc chạy từ laptop:

```bash
curl -X POST http://<pi-ip>:5000/attendance/start \
  -H "content-type: application/json" \
  -d '{"sessionId":91,"cameraId":"cam-imx519-01"}'
```

### 4. Start recording

Nếu attendance stream đang chạy, recording sẽ ghi từ RTSP stream hiện tại. Nếu chưa có stream, recording sẽ mở camera trực tiếp.

Chạy trên Pi:

```bash
curl -X POST http://localhost:5000/recording/start \
  -H "content-type: application/json" \
  -d '{"sessionId":91}'
```

Hoặc chạy từ laptop:

```bash
curl -X POST http://<pi-ip>:5000/recording/start \
  -H "content-type: application/json" \
  -d '{"sessionId":91}'
```

Với `sessionId: 91`, file mặc định sẽ có tên:

```text
session-91.mp4
```

### 5. Check trạng thái

```bash
curl http://localhost:5000/attendance/status
curl http://localhost:5000/recording/status
```

Nếu gọi từ laptop:

```bash
curl http://<pi-ip>:5000/attendance/status
curl http://<pi-ip>:5000/recording/status
```

### 6. Stop recording

```bash
curl -X POST http://localhost:5000/recording/end \
  -H "content-type: application/json" \
  -d '{"recordingId":"session-91"}'
```

Hoặc từ laptop:

```bash
curl -X POST http://<pi-ip>:5000/recording/end \
  -H "content-type: application/json" \
  -d '{"recordingId":"session-91"}'
```

### 7. Video được lưu ở đâu?

Video được lưu trên máy đang chạy edge server. Nếu edge server chạy trên Raspberry Pi, file sẽ nằm trên Pi.

Thư mục lưu video được cấu hình bằng:

```env
RECORDINGS_DIR=recordings
```

Mặc định file nằm trong:

```text
~/apps/multiface-edge-server/recordings/session-91.mp4
```

### 8. Tải video từ Pi về laptop

Chạy lệnh này trên laptop:

```bash
curl -o session-91.mp4 http://<pi-ip>:5000/recording/files/session-91.mp4
```

File sẽ được lưu vào thư mục hiện tại của terminal trên laptop.

Kiểm tra thư mục hiện tại:

```bash
pwd
```

Trên Windows PowerShell cũng có thể dùng:

```powershell
pwd
```

Muốn lưu vào đường dẫn cụ thể trên Windows:

```powershell
curl -o D:\videos\session-91.mp4 http://<pi-ip>:5000/recording/files/session-91.mp4
```

### 9. Stop attendance stream

Sau khi ghi xong, nếu muốn dừng stream attendance:

```bash
curl -X POST http://localhost:5000/attendance/stop \
  -H "content-type: application/json" \
  -d '{"sessionId":91}'
```

Hoặc từ laptop:

```bash
curl -X POST http://<pi-ip>:5000/attendance/stop \
  -H "content-type: application/json" \
  -d '{"sessionId":91}'
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
