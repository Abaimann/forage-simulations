"""Verify the dashboard serves a real page over HTTP."""
import socket
import threading
import time
import urllib.request

from jpm_perspective_grid.infrastructure.dashboard import create_dashboard_app

import tornado.ioloop

app = create_dashboard_app()
probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
probe.bind(("127.0.0.1", 0))
port = probe.getsockname()[1]
probe.close()

app.listen(port, address="127.0.0.1")
loop = tornado.ioloop.IOLoop()
thread = threading.Thread(target=loop.start, daemon=True)
thread.start()
time.sleep(1.0)

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5.0) as response:
        body = response.read().decode("utf-8")
        print("HTTP", response.status, "bytes:", len(body))
        print("has perspective-viewer:", "<perspective-viewer" in body)
        print("has table=quotes:", 'table="quotes"' in body)
        print("has websocket:", "/websocket" in body)
        print("--- first 12 lines ---")
        for line in body.splitlines()[:12]:
            print(line)
finally:
    loop.add_callback(loop.stop)
    thread.join(timeout=5.0)
