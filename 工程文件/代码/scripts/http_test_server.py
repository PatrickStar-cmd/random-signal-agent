"""Real ASGI HTTP server used by offline integration tests."""
import socket
import time
import uvicorn


class LiveServer:
    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self._port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))

    @property
    def server_port(self):
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise TimeoutError('ASGI test server did not become ready')
            time.sleep(0.01)
        return self._port

    def serve_forever(self):
        self.server.run(sockets=[self.socket])

    def shutdown(self):
        self.server.should_exit = True

    def server_close(self):
        # Uvicorn closes the listener after draining requests and lifespan shutdown.
        pass
