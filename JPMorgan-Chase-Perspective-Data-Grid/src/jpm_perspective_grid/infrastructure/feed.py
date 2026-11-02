"""Streaming transport for the mock tick feed.

The wire protocol is deliberately trivial but production friendly:

* transport: TCP;
* framing: newline delimited JSON (one tick per line);
* encoding: UTF-8;
* handshake: the client sends a ``subscribe`` frame and the server answers
  with an ``ack`` frame before any market data is published.

Line delimited JSON keeps the implementation dependency free, is trivially
proxy friendly (a newline survives any TCP middlebox) and allows the reader
to process a partial frame without buffering the whole stream.

Every connected client owns an outbound queue and a dedicated writer
thread.  A slow consumer therefore slows down neither the publisher nor the
other consumers, and the ordering of the frames on the wire is preserved.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Callable, Iterable, Iterator

from ..core.errors import FeedConnectionError, FeedProtocolError
from ..core.models import Tick

#: Maximum size (in bytes) of a single wire frame accepted by the client.
MAX_FRAME_BYTES = 64 * 1024

#: Frame sent by the client to open a subscription.
SUBSCRIBE_FRAME = {"type": "subscribe"}

#: Frame sent by the server to confirm a subscription.
ACK_FRAME = {"type": "ack"}

#: Maximum number of frames buffered per client before it is considered slow.
DEFAULT_QUEUE_SIZE = 4096


class _ClientSession:
    """A single connected consumer with its own outbound queue."""

    __slots__ = (
        "sock",
        "address",
        "_outbox",
        "_lock",
        "_wakeup",
        "_closed",
        "_writer",
        "_queue_size",
    )

    def __init__(
        self, sock: socket.socket, address: tuple[str, int], queue_size: int
    ) -> None:
        self.sock = sock
        self.address = address
        self._outbox: list[bytes] = []
        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._closed = False
        self._writer = threading.Thread(
            target=self._writer_loop, name="tick-feed-writer", daemon=True
        )
        self._queue_size = queue_size

    # -- lifecycle -----------------------------------------------------
    def start_writer(self) -> None:
        """Start the thread draining the outbound queue."""
        self._writer.start()

    def close(self) -> None:
        """Close the session and wake the writer up."""
        self._closed = True
        self._wakeup.set()
        _safe_close(self.sock)

    @property
    def closed(self) -> bool:
        """``True`` once the session has been closed."""
        return self._closed

    # -- queueing ------------------------------------------------------
    def enqueue(self, frame: bytes) -> bool:
        """Queue *frame* for delivery.

        Returns ``False`` when the queue is full, which means the consumer
        is too slow and should be disconnected rather than allowed to blow
        up the server's memory.
        """
        with self._lock:
            if self._closed:
                return False
            if len(self._outbox) >= self._queue_size:
                return False
            self._outbox.append(frame)
        self._wakeup.set()
        return True

    def _writer_loop(self) -> None:
        while not self._closed:
            self._wakeup.wait(timeout=0.2)
            self._wakeup.clear()
            while True:
                with self._lock:
                    if not self._outbox:
                        break
                    frame = self._outbox.pop(0)
                try:
                    self.sock.sendall(frame)
                except OSError:
                    self._closed = True
                    _safe_close(self.sock)
                    return


class TickFeedServer:
    """A tiny TCP server broadcasting ticks to every connected client.

    The server runs an accept loop in a background thread; every connection
    is served by its own writer thread so that a slow consumer can never
    block the others.

    Parameters
    ----------
    host:
        Interface to bind to.
    port:
        Port to bind to; ``0`` picks a free port (the chosen port is then
        available through :attr:`port`).
    backlog:
        Maximum number of pending connections.
    queue_size:
        Maximum number of frames buffered per client.
    handshake_timeout:
        Number of seconds a client has to send its subscription frame.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        backlog: int = 16,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        handshake_timeout: float = 5.0,
    ) -> None:
        self._host = host
        self._requested_port = port
        self._backlog = backlog
        self._queue_size = queue_size
        self._handshake_timeout = handshake_timeout
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._sessions: list[_ClientSession] = []
        self._sessions_lock = threading.Lock()
        self._stop = threading.Event()
        self._bound_port: int | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> "TickFeedServer":
        """Bind the socket and start the accept loop."""
        if self._socket is not None:
            raise FeedConnectionError("server is already running")
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self._host, self._requested_port))
        server_socket.listen(self._backlog)
        server_socket.settimeout(0.05)
        self._socket = server_socket
        self._bound_port = server_socket.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._accept_loop, name="tick-feed-accept", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop the accept loop and close every open connection."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._thread = None
        with self._sessions_lock:
            sessions = list(self._sessions)
            self._sessions.clear()
        for session in sessions:
            session.close()
        server_socket = self._socket
        self._socket = None
        if server_socket is not None:
            _safe_close(server_socket)

    def __enter__(self) -> "TickFeedServer":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def port(self) -> int:
        """The bound port (``0`` until the server has been started)."""
        return self._bound_port if self._bound_port is not None else 0

    @property
    def host(self) -> str:
        """The bound host."""
        return self._host

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        with self._sessions_lock:
            return len(self._sessions)

    def wait_for_clients(self, count: int = 1, timeout: float = 5.0) -> bool:
        """Block until *count* clients are subscribed.

        Returns ``True`` when the expected number of clients showed up
        before the timeout elapsed.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.client_count >= count:
                return True
            time.sleep(0.005)
        return self.client_count >= count

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------
    def broadcast(self, tick: Tick | dict[str, object]) -> int:
        """Send *tick* to every connected client.

        Returns
        -------
        int
            The number of clients the frame was queued for.  Broken or
            overly slow connections are dropped instead of raising.
        """
        return self.broadcast_raw(self._encode(tick))

    def broadcast_many(self, ticks: Iterable[Tick | dict[str, object]]) -> int:
        """Send several ticks, each as its own frame."""
        return sum(self.broadcast(tick) for tick in ticks)

    def broadcast_raw(self, payload: bytes) -> int:
        """Send arbitrary bytes to every connected client.

        The bytes are sent verbatim so that the client's own framing logic
        is exercised; used by the protocol level tests to inject malformed
        frames.
        """
        with self._sessions_lock:
            sessions = list(self._sessions)
        delivered = 0
        for session in sessions:
            if session.enqueue(payload):
                delivered += 1
            else:
                self._drop_session(session)
        return delivered

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _encode(tick: Tick | dict[str, object]) -> bytes:
        payload = tick.to_dict() if isinstance(tick, Tick) else dict(tick)
        try:
            return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise FeedProtocolError(f"tick is not JSON serialisable: {exc}") from exc

    def _accept_loop(self) -> None:
        server_socket = self._socket
        if server_socket is None:  # pragma: no cover - defensive
            return
        while not self._stop.is_set():
            try:
                connection, address = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(
                target=self._handshake,
                args=(connection, address),
                name="tick-feed-handshake",
                daemon=True,
            ).start()

    def _handshake(self, connection: socket.socket, address: tuple[str, int]) -> None:
        """Read the subscription frame and register the client."""
        session = _ClientSession(connection, address, self._queue_size)
        try:
            connection.settimeout(self._handshake_timeout)
            buffer = b""
            while b"\n" not in buffer:
                chunk = connection.recv(1024)
                if not chunk:
                    return
                buffer += chunk
                if len(buffer) > MAX_FRAME_BYTES:
                    return
            line, _, _ = buffer.partition(b"\n")
            try:
                request = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            if not isinstance(request, dict) or request.get("type") != "subscribe":
                return

            # Register before acknowledging so that a client that already
            # received the ack is guaranteed to receive every later tick.
            with self._sessions_lock:
                self._sessions.append(session)
            session.enqueue(
                (json.dumps(ACK_FRAME, separators=(",", ":")) + "\n").encode("utf-8")
            )
            session.start_writer()
        except OSError:
            return
        finally:
            try:
                connection.settimeout(None)
            except OSError:  # pragma: no cover - defensive
                pass

    def _drop_session(self, session: _ClientSession) -> None:
        with self._sessions_lock:
            if session in self._sessions:
                self._sessions.remove(session)
        session.close()


class TickFeedClient:
    """Connects to a :class:`TickFeedServer` and yields ticks.

    Parameters
    ----------
    host:
        Host of the feed server.
    port:
        Port of the feed server.
    timeout:
        Socket timeout in seconds; ``None`` blocks indefinitely.
    on_malformed:
        Callback invoked with the raw payload of a frame that could not be
        decoded.  When omitted, malformed frames raise
        :class:`~jpm_perspective_grid.core.errors.FeedProtocolError`.
    handshake:
        Perform the subscription handshake on connect.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        timeout: float | None = 5.0,
        on_malformed: Callable[[str], None] | None = None,
        handshake: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._on_malformed = on_malformed
        self._handshake = handshake
        self._socket: socket.socket | None = None
        self._buffer = b""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def connect(self) -> "TickFeedClient":
        """Open the TCP connection to the feed server.

        When ``handshake`` is enabled the subscription frame is sent and the
        server's acknowledgement is awaited, so that the client is
        guaranteed to be registered before :meth:`connect` returns.
        """
        if self._socket is not None:
            raise FeedConnectionError("client is already connected")
        try:
            self._socket = socket.create_connection(
                (self._host, self._port), timeout=self._timeout
            )
        except OSError as exc:
            raise FeedConnectionError(
                f"could not connect to {self._host}:{self._port}: {exc}"
            ) from exc
        self._socket.settimeout(self._timeout)
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        if self._handshake:
            try:
                self._socket.sendall(
                    (json.dumps(SUBSCRIBE_FRAME, separators=(",", ":")) + "\n").encode(
                        "utf-8"
                    )
                )
                ack = self._read_line()
                if ack is None:
                    raise FeedConnectionError("feed server closed during handshake")
                payload = json.loads(ack)
                if not isinstance(payload, dict) or payload.get("type") != "ack":
                    raise FeedProtocolError(f"unexpected handshake reply: {ack!r}")
            except (OSError, ValueError) as exc:
                self.close()
                raise FeedConnectionError(f"handshake failed: {exc}") from exc
            except FeedProtocolError:
                self.close()
                raise
        return self

    def close(self) -> None:
        """Close the connection."""
        if self._socket is not None:
            _safe_close(self._socket)
            self._socket = None
        self._buffer = b""

    def __enter__(self) -> "TickFeedClient":
        return self.connect()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def read_tick(self) -> Tick:
        """Read exactly one tick from the feed.

        Raises
        ------
        FeedConnectionError
            When the peer closed the connection.
        FeedProtocolError
            When a frame is malformed and no ``on_malformed`` handler exists.
        """
        line = self._read_line()
        if line is None:
            raise FeedConnectionError("feed server closed the connection")
        try:
            return Tick.from_json(line)
        except Exception:
            if self._on_malformed is not None:
                self._on_malformed(line)
                return self.read_tick()
            raise FeedProtocolError(f"malformed frame: {line!r}")

    def ticks(self) -> Iterator[Tick]:
        """Yield ticks until the server closes the connection."""
        while True:
            try:
                tick = self.read_tick()
            except FeedConnectionError:
                return
            yield tick

    def read_ticks(self, count: int) -> list[Tick]:
        """Read exactly *count* ticks."""
        if count < 0:
            raise ValueError(f"count must not be negative, got {count}")
        result: list[Tick] = []
        for tick in self.ticks():
            result.append(tick)
            if len(result) >= count:
                break
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _read_line(self) -> str | None:
        sock = self._socket
        if sock is None:
            raise FeedConnectionError("client is not connected")
        while b"\n" not in self._buffer:
            try:
                chunk = sock.recv(4096)
            except socket.timeout as exc:
                raise FeedConnectionError(f"timed out reading from feed: {exc}") from exc
            except OSError as exc:
                raise FeedConnectionError(f"connection error: {exc}") from exc
            if not chunk:
                if not self._buffer:
                    return None
                # Server closed mid-frame: hand over the remainder so that
                # the caller can report it as a protocol error.
                payload = self._buffer
                self._buffer = b""
                return payload.decode("utf-8", errors="replace")
            self._buffer += chunk
            if len(self._buffer) > MAX_FRAME_BYTES:
                raise FeedProtocolError(
                    f"frame exceeds {MAX_FRAME_BYTES} bytes without a newline"
                )
        line, _, remainder = self._buffer.partition(b"\n")
        self._buffer = remainder
        return line.decode("utf-8", errors="replace")


def _safe_close(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:  # pragma: no cover - defensive
        pass
