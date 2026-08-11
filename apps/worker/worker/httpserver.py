"""A tiny stdlib HTTP server for ``/metrics`` and ``/healthz``.

The worker has no web framework, and it does not need one — but it does need
to be scrapeable and probeable, so it serves exactly two paths on port 9000.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

logger = logging.getLogger("worker.http")


class _Handler(BaseHTTPRequestHandler):
    """Serves /metrics and /healthz; 404 for everything else."""

    protocol_version = "HTTP/1.1"
    server_version = "preview-worker"
    sys_version = ""

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Method name is mandated by BaseHTTPRequestHandler.
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        if path == "/metrics":
            self._respond(200, generate_latest(REGISTRY), CONTENT_TYPE_LATEST)
        elif path in ("/healthz", "/"):
            body = json.dumps({"status": "ok", "service": "worker"}).encode()
            self._respond(200, body, "application/json")
        else:
            body = json.dumps({"status": "not_found"}).encode()
            self._respond(404, body, "application/json")

    def log_message(self, format: str, *args: Any) -> None:
        """Route the server's own chatter into the JSON logger at DEBUG."""
        logger.debug(
            "worker http request",
            extra={"event": "http.request", "detail": format % args},
        )


def start_metrics_server(port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Start the metrics/health server on a daemon thread and return it."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="worker-http", daemon=True)
    thread.start()
    logger.info(
        "metrics server listening",
        extra={"event": "http.started", "host": host, "port": port},
    )
    return server
