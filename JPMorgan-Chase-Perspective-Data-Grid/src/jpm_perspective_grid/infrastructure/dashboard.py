"""Browser facing dashboard for the live Perspective grid.

The module serves a single page application that embeds ``<perspective-viewer>``
and connects it to the live table over a WebSocket.  Everything is optional:
if ``perspective-python`` or ``tornado`` is not installed, the dashboard
raises a descriptive error while the rest of the package keeps working.
"""

from __future__ import annotations

import json
from typing import Any

from .sinks import PERSPECTIVE_SCHEMA

#: Minimal single page application embedding the Perspective viewer.
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>J.P. Morgan - Live Perspective Grid</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@perspective-viewer@2.4.0/dist/css/perspective-viewer.css" />
<script src="https://cdn.jsdelivr.net/npm/@perspective-viewer@2.4.0/dist/cdn/perspective-viewer.js"></script>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
         background: #10131a; color: #e6e9ef; }
  h1 { font-size: 18px; font-weight: 600; margin: 0 0 16px; }
  #status { margin-bottom: 16px; font-size: 13px; color: #8b93a7; }
  perspective-viewer { width: 100%; height: 70vh; }
</style>
</head>
<body>
  <h1>J.P. Morgan &amp; Co. &mdash; Live Perspective Data Grid</h1>
  <div id="status">connecting...</div>
  <perspective-viewer id="grid" table="quotes" columns="stock" rows="price"
                      pivots="kind" aggregates="ratio,upper_bound,lower_bound"
                      filters="trigger_alert = true"></perspective-viewer>
  <script>
    const viewer = document.getElementById("grid");
    const status = document.getElementById("status");
    const socket = new WebSocket("ws://" + location.host + "/websocket");
    socket.onopen = () => { status.textContent = "connected to the live grid"; };
    socket.onclose = () => { status.textContent = "disconnected"; };
    socket.onerror = () => { status.textContent = "connection error"; };
  </script>
</body>
</html>
"""


class DashboardError(RuntimeError):
    """Raised when the dashboard cannot be started."""


def build_perspective_server() -> Any:
    """Create a Perspective server exposing a table named ``quotes``."""
    try:
        import perspective  # noqa: PLC0415  (optional dependency)
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise DashboardError(
            "perspective-python is required for the dashboard; install it with "
            "`pip install perspective-python`"
        ) from exc

    server = perspective.Server()
    client = server.new_local_client()
    client.table(dict(PERSPECTIVE_SCHEMA), name="quotes")
    return server


def create_dashboard_app(
    perspective_server: Any | None = None,
) -> Any:
    """Build the Tornado application serving the dashboard and the WebSocket.

    Parameters
    ----------
    perspective_server:
        An existing Perspective server.  A new one is created when omitted.
    """
    try:
        import tornado.web  # noqa: PLC0415  (optional dependency)
        from perspective.handlers.tornado import (  # noqa: PLC0415
            PerspectiveTornadoHandler,
        )
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise DashboardError(
            "tornado and perspective-python are required for the dashboard"
        ) from exc

    server = perspective_server or build_perspective_server()

    class _IndexHandler(tornado.web.RequestHandler):
        def get(self) -> None:  # noqa: D102 - tornado API
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(DASHBOARD_HTML)

    return tornado.web.Application(
        [
            (r"/", _IndexHandler),
            (
                r"/websocket",
                PerspectiveTornadoHandler,
                {"perspective_server": server},
            ),
        ]
    )


def serve_dashboard(
    host: str = "127.0.0.1",
    port: int = 8888,
    perspective_server: Any | None = None,
) -> None:
    """Run the dashboard until interrupted.

    This blocks the calling thread; it is meant to be used from a script.
    """
    try:
        import tornado.ioloop  # noqa: PLC0415  (optional dependency)
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise DashboardError("tornado is required for the dashboard") from exc

    app = create_dashboard_app(perspective_server)
    app.listen(port, address=host)
    print(f"dashboard available at http://{host}:{port}")
    tornado.ioloop.IOLoop.current().start()


def dashboard_payload(rows: list[dict[str, Any]]) -> str:
    """Serialise grid rows for a non WebSocket consumer."""
    return json.dumps(rows, separators=(",", ":"), default=str)
