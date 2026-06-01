# Raspberry Pi Deployment Runbook

This runbook targets a `demo stable` deployment where:

- Raspberry Pi, backend, and AI service share the same LAN or hotspot
- the Pi runs the Flask edge server as a `systemd` service
- the Pi publishes RTSP and does not run recognition inference

## 1. Verify OS and network

Run on the Pi:

```bash
uname -a
cat /etc/os-release
hostname -I
```

Confirm:

- Raspberry Pi OS is available
- the Pi has an IP reachable by backend and AI service

## 2. Install system dependencies

Use Raspberry Pi OS package manager:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg curl
```

Verify camera tools:

```bash
which rpicam-vid || which libcamera-vid
which rpicam-still || which libcamera-still
```

Install `mediamtx` if missing. If it is not available from apt, download the Linux ARM64 release and place the binary somewhere in `PATH`, for example `/usr/local/bin/mediamtx`.

Verify:

```bash
which mediamtx
which ffmpeg
```

## 3. Copy project and create venv

Example:

```bash
mkdir -p ~/apps
cd ~/apps
```

Copy `multiface-edge-server` to the Pi, then:

```bash
cd ~/apps/multiface-edge-server
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Create `.env`

Example:

```env
BACKEND_URL=http://<backend-ip>:3000
BACKEND_EDGE_TOKEN=test-internal-token
DEVICE_CODE=pi-room-a-01
DEVICE_NAME=Raspberry Pi Room A
ROOM_CODE=A101
CAMERA_ID=cam-imx519-01
CONTROL_BASE_URL=http://<pi-ip>:5000
STREAM_BASE_URL=rtsp://<pi-ip>:8554
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

## 5. Dry run manually before systemd

```bash
cd ~/apps/multiface-edge-server
source .venv/bin/activate
python run_edge_server.py
```

Expected checks:

- preflight succeeds
- edge device registers into backend
- heartbeat updates `last_heartbeat_at`
- `curl http://localhost:5000/health` returns OK

If camera is not detected:

```bash
rpicam-still --list-cameras
libcamera-still --list-cameras
```

If backend is not reachable:

```bash
curl http://<backend-ip>:3000
```

## 6. Install systemd service

Copy the unit file:

```bash
sudo cp deploy/raspberry-pi/multiface-edge.service /etc/systemd/system/multiface-edge.service
```

Edit these fields if your path is different:

- `WorkingDirectory`
- `EnvironmentFile`
- `ExecStart`

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable multiface-edge
sudo systemctl start multiface-edge
```

## 7. Operate and debug

Service status:

```bash
sudo systemctl status multiface-edge
```

Live logs:

```bash
journalctl -u multiface-edge -f
```

Health:

```bash
curl http://localhost:5000/health
curl http://localhost:5000/attendance/status
```

## 8. Manual control test from laptop

On a laptop in the same LAN:

```bash
curl -X POST http://<pi-ip>:5000/attendance/start \
  -H "content-type: application/json" \
  -d '{"sessionId":91,"cameraId":"cam-imx519-01"}'
```

Check status:

```bash
curl http://<pi-ip>:5000/attendance/status
```

Stop:

```bash
curl -X POST http://<pi-ip>:5000/attendance/stop \
  -H "content-type: application/json" \
  -d '{"sessionId":91}'
```

## 9. Full-flow acceptance

- backend sees the edge device as `online` before session start
- backend can create a session with `pi-room-a-01`
- edge returns a valid RTSP `streamUrl`
- AI service can open the stream
- edge can start and stop a recording, and returns a local `.mp4` file path
- frontend live monitor shows:
  - `Edge online`
  - `Stream running`
  - `AI running`
