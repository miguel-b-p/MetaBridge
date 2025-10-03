# src/client.py
"""High-performance client for MetaBridge services using sockets."""
from __future__ import annotations

import socket
import struct
from contextlib import contextmanager
from queue import Full, Queue
from typing import Any, Callable, Dict, Generator, List

import msgpack

from .exceptions import RemoteExecutionError, ServiceNotFound
from .registry import resolve_service


class ServiceClient:
    """High-performance client using TCP sockets for low-latency communication."""

    def __init__(
        self,
        name: str,
        *ctor_args: Any,
        timeout: float = 5.0,
        poll_interval: float = 0.002,
        max_pool_size: int = 16,
        **ctor_kwargs: Any,
    ) -> None:
        self._name = name
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._ctor_args = list(ctor_args)
        self._ctor_kwargs = dict(ctor_kwargs)
        self._closed = False
        self._max_pool_size = max_pool_size

        # Get service connection info
        service_info = resolve_service(name)
        self._host = service_info.host
        self._port = service_info.port

        # Connection pooling for better performance and thread-safety
        self._socket_pool: Queue[socket.socket] = Queue(maxsize=self._max_pool_size)

        # Cache endpoints
        self._endpoints: List[str] = self._fetch_endpoints()

    def _get_socket(self) -> socket.socket:
        """Get a socket from the pool or create a new one."""
        if not self._socket_pool.empty():
            try:
                return self._socket_pool.get_nowait()
            except Exception:
                pass  # Fallback to creating a new socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # Disable Nagle's algorithm
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # Enable keepalive
        sock.settimeout(self._timeout)
        sock.connect((self._host, self._port))
        return sock

    def _return_socket(self, sock: socket.socket) -> None:
        """Return a socket to the pool if it's not full."""
        if self._closed:
            sock.close()
            return
        try:
            self._socket_pool.put_nowait(sock)
        except Full:
            sock.close()

    @contextmanager
    def _managed_socket(self) -> Generator[socket.socket, None, None]:
        """Provides a socket from the pool and ensures it's returned or closed."""
        if self._closed:
            raise RuntimeError("ServiceClient is closed.")

        sock = self._get_socket()
        try:
            yield sock
            # If everything went well, return the socket to the pool
            self._return_socket(sock)
        except Exception:
            # If an error occurred, close the socket to prevent a corrupted state
            sock.close()
            raise

    def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send request and receive response using a managed socket."""
        try:
            with self._managed_socket() as sock:
                # Serialize with msgpack (faster and safer than pickle)
                data = msgpack.packb(payload, use_bin_type=True)

                # Send length header (4 bytes) + data
                sock.sendall(struct.pack("!I", len(data)) + data)

                # Receive response length
                length_bytes = sock.recv(4)
                if not length_bytes:
                    raise RemoteExecutionError("Connection closed by server")

                response_length = struct.unpack("!I", length_bytes)[0]

                # Receive response data
                response_data = b""
                while len(response_data) < response_length:
                    chunk = sock.recv(min(4096, response_length - len(response_data)))
                    if not chunk:
                        raise RemoteExecutionError("Connection closed while reading response")
                    response_data += chunk

                return msgpack.unpackb(response_data, raw=False)

        except Exception as exc:
            if isinstance(exc, RemoteExecutionError):
                raise
            raise RemoteExecutionError(f"Request failed: {exc}") from exc

    def _fetch_endpoints(self) -> List[str]:
        response = self._send_request({"type": "list_endpoints"})
        if response.get("status") != "ok":
            raise RemoteExecutionError(f"Unable to query endpoints: {response}")
        return list(response.get("result", []))

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def call_remote(*args: Any, **kwargs: Any) -> Any:
            payload = {
                "type": "call",
                "endpoint": name,
                "args": args,
                "kwargs": kwargs,
                "ctor_args": self._ctor_args,
                "ctor_kwargs": self._ctor_kwargs,
            }

            response = self._send_request(payload)

            if response.get("status") == "ok":
                return response.get("result")

            error = response.get("error", {})
            raise RemoteExecutionError(
                f"Remote call to '{self._name}.{name}' failed:\n"
                f"  Type: {error.get('type')}\n"
                f"  Message: {error.get('message')}"
            )

        return call_remote

    def endpoints(self) -> List[str]:
        return list(self._endpoints)

    def close(self) -> None:
        """Close the client and all pooled socket connections."""
        if self._closed:
            return
        self._closed = True
        while not self._socket_pool.empty():
            try:
                sock = self._socket_pool.get_nowait()
                sock.close()
            except Exception:
                pass

    def __enter__(self) -> "ServiceClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def connect_service(
    name: str,
    *ctor_args: Any,
    timeout: float = 5.0,
    poll_interval: float = 0.002,
    **ctor_kwargs: Any,
) -> ServiceClient:
    try:
        return ServiceClient(
            name,
            *ctor_args,
            timeout=timeout,
            poll_interval=poll_interval,
            **ctor_kwargs,
        )
    except ServiceNotFound as exc:
        raise ServiceNotFound(f"Unable to connect to service '{name}': {exc}") from exc