# src/server.py
"""High-performance server using sockets and memory-mapped communication."""
from __future__ import annotations

import asyncio
import atexit
import multiprocessing
import os
import socket
import struct
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.context import BaseContext
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Optional, Tuple

import msgpack

from .config import DEFAULT_HOST
from .exceptions import MetaBridgeError, ServiceNotFound
from .registry import ServiceRecord, find_free_port, register_service, resolve_service, unregister_service

JsonDict = Dict[str, Any]
EndpointSpec = Tuple[str, Callable[..., Any]]
CallableFactory = Callable[[List[Any], Dict[str, Any]], Callable[..., Any]]

_ACTIVE_DAEMONS: List["DaemonHandle"] = []
_DAEMON_CLEANUP_REGISTERED = False


def _compute_worker_count() -> int:
    workers_env = os.environ.get("META_WORKERS")
    try:
        workers = int(workers_env) if workers_env else 0
    except (ValueError, TypeError):
        workers = 0
    if workers <= 0:
        cpu = os.cpu_count() or 1
        workers = min(32, max(4, cpu * 2))
    return workers


def _register_daemon_handle(handle: "DaemonHandle") -> None:
    global _DAEMON_CLEANUP_REGISTERED
    _ACTIVE_DAEMONS.append(handle)
    if not _DAEMON_CLEANUP_REGISTERED:
        atexit.register(_shutdown_daemons)
        _DAEMON_CLEANUP_REGISTERED = True


def _unregister_daemon_handle(handle: "DaemonHandle") -> None:
    try:
        _ACTIVE_DAEMONS.remove(handle)
    except ValueError:
        pass


def _shutdown_daemons() -> None:
    for handle in list(_ACTIVE_DAEMONS):
        try:
            handle.stop(timeout=0.5)
        except Exception:
            pass


class _FunctionFactory:
    def __init__(self, func: Callable[..., Any]) -> None:
        self._func = func

    def __call__(self, _ctor_args: List[Any], _ctor_kwargs: Dict[str, Any]) -> Callable[..., Any]:
        return self._func


class _InstanceMethodFactory:
    """Efficient LRU cache for service class instances."""

    def __init__(self, cls: type, attr_name: str, max_size: int = 128) -> None:
        self._cls = cls
        self._attr_name = attr_name
        self._cache: OrderedDict[tuple, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def __call__(self, ctor_args: List[Any], ctor_kwargs: Dict[str, Any]) -> Callable[..., Any]:
        key = (tuple(ctor_args), tuple(sorted(ctor_kwargs.items())))

        with self._lock:
            instance = self._cache.get(key)
            if instance is not None:
                # Mark as recently used
                self._cache.move_to_end(key)
            else:
                # Evict least recently used if cache is full
                if len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                # Create and cache new instance
                instance = self._cls(*ctor_args, **ctor_kwargs)
                self._cache[key] = instance

        return getattr(instance, self._attr_name)


class _StaticLikeFactory:
    def __init__(self, owner: type, attr_name: str) -> None:
        self._owner = owner
        self._attr_name = attr_name

    def __call__(self, _ctor_args: List[Any], _ctor_kwargs: Dict[str, Any]) -> Callable[..., Any]:
        return getattr(self._owner, self._attr_name)


class RegisteredFunction:
    """Internal wrapper that knows how to produce a callable target."""

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        factory: CallableFactory | None = None,
    ) -> None:
        self.name = name
        self.func = func
        self.factory = factory or (lambda *_: func)

    def invoke(
        self,
        args: List[Any],
        kwargs: Dict[str, Any],
        ctor_args: List[Any],
        ctor_kwargs: Dict[str, Any],
    ) -> Any:
        target = self.factory(ctor_args, ctor_kwargs)
        result = target(*args, **kwargs)
        if asyncio.iscoroutine(result):
            # The ThreadPoolExecutor model runs async functions in a managed event loop
            return asyncio.run(result)
        return result


class ServiceServer:
    """High-performance server using TCP sockets for ultra-low latency."""

    def __init__(self, name: str, host: Optional[str] = None) -> None:
        self._name = name
        self._registry: Dict[str, RegisteredFunction] = {}
        self._lock = threading.Lock()
        self._server_socket: Optional[socket.socket] = None
        self._host = host or DEFAULT_HOST
        self._port = find_free_port(self._host)
        self._running = threading.Event()
        self._record: Optional[ServiceRecord] = None
        self._frozen = False

        # Thread pool for concurrent request handling
        self._executor: Optional[ThreadPoolExecutor] = None
        self._create_executor()

        # Server thread
        self._server_thread: Optional[threading.Thread] = None

    def _create_executor(self) -> None:
        if self._executor is None:
            workers = _compute_worker_count()
            self._executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix=f"MetaBridge-exec[{self._name}]",
            )

    @property
    def name(self) -> str:
        return self._name

    @property
    def endpoints(self) -> MappingProxyType:
        with self._lock:
            return MappingProxyType({name: entry.func for name, entry in self._registry.items()})

    def _resolve_factory(self, func: Callable[..., Any], name: str) -> CallableFactory:
        owner = getattr(func, "metabridge_owner", None)
        attr_name = getattr(func, "metabridge_attr", name)
        descriptor = getattr(func, "metabridge_descriptor", "instance")

        if owner is None:
            return _FunctionFactory(func)
        if descriptor in {"staticmethod", "classmethod"}:
            return _StaticLikeFactory(owner, attr_name)
        return _InstanceMethodFactory(owner, attr_name)

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        factory: CallableFactory | None = None,
    ) -> None:
        with self._lock:
            if self._frozen:
                raise MetaBridgeError("Service is running as a daemon; no new endpoints can be registered")
            if name in self._registry:
                raise MetaBridgeError(f"Endpoint '{name}' is already registered")
            resolved_factory = factory or self._resolve_factory(func, name)
            self._registry[name] = RegisteredFunction(name, func, resolved_factory)

    def start(self, *, daemon_thread: bool = True) -> None:
        if self._server_thread and self._server_thread.is_alive():
            return

        self._running.set()
        self._create_executor()

        # Create server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._server_socket.bind((self._host, self._port))
        self._server_socket.listen(128)  # High backlog for concurrent connections

        self._server_thread = threading.Thread(
            target=self._serve_loop,
            name=f"MetaBridge[{self._name}]",
            daemon=daemon_thread,
        )
        self._server_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._running.clear()

        # Close server socket to interrupt accept()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        # Wait for server thread
        thread = self._server_thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._server_thread = None

        # Shutdown executor
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None

        # Unregister from registry
        if self._record:
            unregister_service(self._name, expected_pid=self._record.pid)
            self._record = None

    def set_frozen(self, value: bool) -> None:
        with self._lock:
            self._frozen = value

    def publish(self) -> ServiceRecord:
        if self._record is not None:
            return self._record

        record = ServiceRecord(name=self._name, host=self._host, port=self._port, pid=os.getpid())
        register_service(record)
        atexit.register(lambda: unregister_service(record.name, expected_pid=record.pid))
        self._record = record
        return record

    def run_forever(self, *, poll_interval: float = 0.5) -> None:
        """Block the current thread while the service keeps handling requests."""
        self.start()
        self.publish()

        try:
            while True:
                if not self._running.is_set():
                    break
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def snapshot_registry(self) -> List[EndpointSpec]:
        with self._lock:
            return [(name, entry.func) for name, entry in self._registry.items()]

    def _serve_loop(self) -> None:
        """Main server loop accepting connections."""
        while self._running.is_set():
            try:
                # Accept with timeout to check running flag periodically
                if self._server_socket is None:
                    break
                self._server_socket.settimeout(0.1)
                client_socket, _ = self._server_socket.accept()

                # Handle in thread pool for concurrency
                if self._executor:
                    self._executor.submit(self._handle_client, client_socket)
                else:
                    # Fallback for immediate execution if executor is gone
                    self._handle_client(client_socket)

            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, client_socket: socket.socket) -> None:
        """Handle a single client connection."""
        try:
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            while self._running.is_set():
                # Read message length (4 bytes)
                length_bytes = client_socket.recv(4)
                if not length_bytes:
                    break

                message_length = struct.unpack("!I", length_bytes)[0]

                # Read message data
                data = b""
                while len(data) < message_length:
                    chunk = client_socket.recv(min(4096, message_length - len(data)))
                    if not chunk:
                        break
                    data += chunk

                if len(data) < message_length:
                    break

                # Process request
                request = msgpack.unpackb(data, raw=False)
                response = self.handle_request(request)

                # Send response
                response_data = msgpack.packb(response, use_bin_type=True)
                client_socket.sendall(struct.pack("!I", len(response_data)) + response_data)

        except Exception:
            pass
        finally:
            client_socket.close()

    def handle_request(self, request: JsonDict) -> JsonDict:
        """Process a request and return response."""
        command = request.get("type")

        if command == "list_endpoints":
            with self._lock:
                return {"status": "ok", "result": sorted(self._registry.keys())}

        if command != "call":
            return {
                "status": "error",
                "error": {"type": "ProtocolError", "message": "Unknown command"},
            }

        endpoint = str(request.get("endpoint"))
        args = list(request.get("args", []))
        kwargs = dict(request.get("kwargs", {}))
        ctor_args = list(request.get("ctor_args", []))
        ctor_kwargs = dict(request.get("ctor_kwargs", {}))

        with self._lock:
            callable_entry = self._registry.get(endpoint)

        if callable_entry is None:
            return {
                "status": "error",
                "error": {"type": "NotFound", "message": f"Endpoint '{endpoint}' not found"},
            }

        try:
            result = callable_entry.invoke(args, kwargs, ctor_args, ctor_kwargs)
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {
                "status": "error",
                "error": {"type": exc.__class__.__name__, "message": str(exc)},
            }


class ServiceBuilder:
    """Public API exposed to user-land to register functions."""

    def __init__(self, server: ServiceServer, *, bootstrap: bool = True):
        self._server = server
        if bootstrap:
            self._server.start()
            self._server.publish()

    def register(
        self,
        explicit_name: str | None = None,
        *,
        alias: str | None = None,
        factory: CallableFactory | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            endpoint_name = explicit_name or func.__name__
            self._server.register(endpoint_name, func, factory=factory)
            if alias and alias != endpoint_name:
                self._server.register(alias, func, factory=factory)
            return func

        return decorator

    def _register_endpoint(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        factory: CallableFactory | None = None,
    ) -> None:
        self._server.register(name, func, factory=factory)

    def routes(self) -> Dict[str, Callable[..., Any]]:
        return dict(self._server.endpoints)

    def daemon(self) -> "DaemonServiceBuilder":
        self._server.stop()
        return DaemonServiceBuilder(self._server, bootstrap=False)


class DaemonHandle:
    """Represents a background MetaBridge daemon process."""

    def __init__(
        self,
        service_name: str,
        process: multiprocessing.Process,
        cleanup: Callable[["DaemonHandle"], None] | None = None,
    ) -> None:
        self._service_name = service_name
        self._process = process
        self._cleanup = cleanup
        self._stopped = False

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid

    @property
    def service(self) -> str:
        return self._service_name

    def is_running(self) -> bool:
        return self._process.is_alive() and not self._stopped

    def stop(self, *, timeout: float = 1.0) -> None:
        if self._stopped:
            return

        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=timeout)
        else:
            self._process.join(timeout=timeout)

        unregister_service(self._service_name, expected_pid=self.pid)
        self._stopped = True

        if self._cleanup:
            self._cleanup(self)
            self._cleanup = None

    def join(self, timeout: Optional[float] = None) -> None:
        self._process.join(timeout)


class DaemonServiceBuilder(ServiceBuilder):
    """Builder variant that exposes convenience helpers for daemon services."""

    def __init__(self, server: ServiceServer, *, bootstrap: bool = True):
        super().__init__(server, bootstrap=bootstrap)
        self._handle: Optional[DaemonHandle] = None

    def run(
        self,
        *,
        poll_interval: float = 0.5,
        wait: bool = False,
        startup_timeout: float = 5.0,
    ) -> DaemonHandle:
        if self._handle and self._handle.is_running():
            raise MetaBridgeError("Daemon is already running for this service")

        endpoints = self._server.snapshot_registry()
        if not endpoints:
            raise MetaBridgeError("Cannot run daemon without at least one registered endpoint")

        self._server.set_frozen(True)
        self._server.stop()

        def _cleanup(handle: DaemonHandle) -> None:
            if self._handle is handle:
                self._handle = None
            _unregister_daemon_handle(handle)
            self._server.set_frozen(False)

        process = _spawn_daemon_process(self._server.name, endpoints, poll_interval)
        handle = DaemonHandle(self._server.name, process, cleanup=_cleanup)

        try:
            _await_service_start(self._server.name, timeout=startup_timeout)
        except Exception:
            handle.stop(timeout=0.5)
            raise

        self._handle = handle
        _register_daemon_handle(handle)

        if wait:
            try:
                process.join()
            except KeyboardInterrupt:
                handle.stop()

        return handle


def create_service(name: str, host: Optional[str] = None) -> ServiceBuilder:
    server = ServiceServer(name=name, host=host)
    return ServiceBuilder(server)


def _spawn_daemon_process(
    name: str, endpoints: List[EndpointSpec], poll_interval: float
) -> multiprocessing.Process:
    try:
        ctx: BaseContext = multiprocessing.get_context("fork")
    except ValueError:
        ctx = multiprocessing.get_context("spawn")

    process = ctx.Process(
        target=_daemon_worker,
        args=(name, endpoints, poll_interval),
        daemon=False,
        name=f"MetaBridge-daemon[{name}]",
    )
    process.start()
    return process


def _daemon_worker(name: str, endpoints: List[EndpointSpec], poll_interval: float) -> None:
    server = ServiceServer(name)
    for endpoint_name, func in endpoints:
        server.register(endpoint_name, func)
    server.run_forever(poll_interval=poll_interval)


def _await_service_start(name: str, *, timeout: float) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            resolve_service(name)
            return
        except ServiceNotFound:
            time.sleep(0.01)  # Much shorter sleep for faster startup
    raise MetaBridgeError(f"Service '{name}' did not start within {timeout:.1f}s")