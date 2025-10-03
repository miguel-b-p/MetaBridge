"""High-performance client for MetaBridge services using sockets."""
from __future__ import annotations

import pickle
import socket
import struct
from typing import Any, Callable, Dict, List

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
        **ctor_kwargs: Any,
    ) -> None:
        self._name = name
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._ctor_args = list(ctor_args)
        self._ctor_kwargs = dict(ctor_kwargs)
        self._socket_pool: List[socket.socket] = []

        # Get service connection info
        service_info = resolve_service(name)
        self._host = service_info.host
        self._port = service_info.port

        # Connection pooling for better performance
        self._max_pool_size = 10

        # Cache endpoints
        self._endpoints: List[str] = self._fetch_endpoints()

    def _get_socket(self) -> socket.socket:
        """Get a socket from the pool or create a new one."""
        if self._socket_pool:
            return self._socket_pool.pop()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # Disable Nagle's algorithm
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # Enable keepalive
        sock.settimeout(self._timeout)
        sock.connect((self._host, self._port))
        return sock

    def _return_socket(self, sock: socket.socket) -> None:
        """Return a socket to the pool."""
        if len(self._socket_pool) < self._max_pool_size:
            self._socket_pool.append(sock)
        else:
            sock.close()

    def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send request and receive response using binary protocol."""
        sock = None
        try:
            sock = self._get_socket()

            # Serialize with pickle (much faster than JSON)
            data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)

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

            response = pickle.loads(response_data)

            # Return socket to pool for reuse
            self._return_socket(sock)
            return response

        except Exception as exc:
            if sock:
                sock.close()
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

    def __del__(self):
        """Close all pooled sockets on cleanup."""
        if not hasattr(self, "_socket_pool"):
            return
        for sock in self._socket_pool:
            try:
                sock.close()
            except Exception:
                pass


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