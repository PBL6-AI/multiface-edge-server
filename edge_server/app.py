from __future__ import annotations

import atexit
import logging

from dotenv import load_dotenv
from flask import Flask, jsonify, request

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
