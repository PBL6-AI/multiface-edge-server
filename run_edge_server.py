from edge_server.app import app, camera_edge_service


if __name__ == "__main__":
    camera_edge_service.register()
    app.run(host="0.0.0.0", port=5000)
