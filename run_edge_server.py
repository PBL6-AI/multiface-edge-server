from edge_server.app import app, camera_edge_service, config


if __name__ == "__main__":
    preflight = camera_edge_service.preflight_check()
    print(f"Edge preflight result: {preflight}")
    camera_edge_service.register()
    app.run(host="0.0.0.0", port=config.port)
