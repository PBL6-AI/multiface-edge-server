from __future__ import annotations

import atexit
import logging

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

from .backend_client import BackendClient
from .camera_service import CameraEdgeService
from .config import EdgeServerConfig

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = EdgeServerConfig()
backend_client = BackendClient(
    config.backend_url,
    config.edge_token,
    retry_attempts=config.backend_retry_attempts,
    retry_delay_seconds=config.backend_retry_delay_seconds,
)
camera_edge_service = CameraEdgeService(config, backend_client)


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "deviceCode": config.device_code,
                "cameraId": config.camera_id,
                "runtime": camera_edge_service.status(),
            }
        )

    @app.post("/attendance/start")
    def start_attendance():
        payload = request.get_json(force=True, silent=False) or {}
        session_id = payload.get("sessionId")
        if session_id is None:
            return jsonify({"message": "sessionId is required"}), 400

        camera_id = payload.get("cameraId") or config.camera_id
        try:
            result = camera_edge_service.start(session_id=session_id, camera_id=camera_id)
            return jsonify(result), 200
        except Exception as exc:
            logger.exception("Failed to start attendance stream")
            return jsonify({"message": str(exc)}), 500

    @app.post("/attendance/stop")
    def stop_attendance():
        payload = request.get_json(force=True, silent=False) or {}
        session_id = payload.get("sessionId")
        if session_id is None:
            return jsonify({"message": "sessionId is required"}), 400

        try:
            result = camera_edge_service.stop(session_id=session_id)
            return jsonify(result), 200
        except Exception as exc:
            logger.exception("Failed to stop attendance stream")
            return jsonify({"message": str(exc)}), 500

    @app.get("/attendance/status")
    def attendance_status():
        return jsonify(camera_edge_service.status()), 200

    @app.post("/preview/start")
    def start_preview():
        payload = request.get_json(force=True, silent=True) or {}
        try:
            result = camera_edge_service.start_preview(
                stream_path=payload.get("streamPath")
            )
            return jsonify(result), 200
        except Exception as exc:
            logger.exception("Failed to start enrollment preview")
            return jsonify({"message": str(exc)}), 500

    @app.post("/preview/stop")
    def stop_preview():
        try:
            result = camera_edge_service.stop_preview()
            return jsonify(result), 200
        except Exception as exc:
            logger.exception("Failed to stop enrollment preview")
            return jsonify({"message": str(exc)}), 500

    @app.post("/recording/start")
    def start_recording():
        payload = request.get_json(force=True, silent=False) or {}
        recording_id = payload.get("recordingId")
        if recording_id is None and payload.get("sessionId") is not None:
            recording_id = f"session-{payload['sessionId']}"

        try:
            result = camera_edge_service.start_recording(
                recording_id=recording_id,
                file_name=payload.get("fileName"),
            )
            return jsonify(result), 200
        except Exception as exc:
            logger.exception("Failed to start camera recording")
            return jsonify({"message": str(exc)}), 500

    @app.post("/recording/stop")
    @app.post("/recording/end")
    def stop_recording():
        payload = request.get_json(force=True, silent=True) or {}
        try:
            result = camera_edge_service.stop_recording(
                recording_id=payload.get("recordingId")
            )
            return jsonify(result), 200
        except Exception as exc:
            logger.exception("Failed to stop camera recording")
            return jsonify({"message": str(exc)}), 500

    @app.get("/recording/status")
    def recording_status():
        return jsonify(camera_edge_service.recording_status()), 200

    @app.get("/recording/files/<path:file_name>")
    def download_recording(file_name: str):
        return send_from_directory(
            config.recordings_dir,
            file_name,
            as_attachment=True,
        )

    return app


app = create_app()


@atexit.register
def _shutdown():
    camera_edge_service.shutdown()


if __name__ == "__main__":
    preflight = camera_edge_service.preflight_check()
    logger.info("Edge preflight result: %s", preflight)
    camera_edge_service.register()
    app.run(host="0.0.0.0", port=config.port)
