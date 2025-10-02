"""In-memory service registry using multiprocessing.Manager for IPC."""
from __future__ import annotations

import os
import multiprocessing
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .exceptions import ServiceAlreadyExists, ServiceNotFound

# Global manager for sharing service registry across processes
_manager: Optional[multiprocessing.managers.SyncManager] = None
_registry: Optional[Dict[str, Dict[str, Any]]] = None
_lock: Optional[multiprocessing.synchronize.Lock] = None

def _get_manager() -> multiprocessing.managers.SyncManager:
    """Get or create the global manager."""
    global _manager, _registry, _lock
    if _manager is None:
        _manager = multiprocessing.Manager()
        _registry = _manager.dict()
        _lock = _manager.Lock()
    return _manager

def _get_registry() -> Dict[str, Dict[str, Any]]:
    """Get the shared registry dict."""
    _get_manager()
    return _registry  # type: ignore

def _get_lock() -> multiprocessing.synchronize.Lock:
    """Get the shared lock."""
    _get_manager()
    return _lock  # type: ignore

@dataclass
class ServiceRecord:
    """Metadata stored for each registered service."""
    name: str
    host: str
    port: int
    pid: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceRecord":
        return cls(
            name=data["name"],
            host=data["host"],
            port=data["port"],
            pid=int(data["pid"])
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "pid": self.pid
        }

def _is_process_alive(pid: int) -> bool:
    """Check if a process is still running."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True

def register_service(record: ServiceRecord) -> None:
    """Register a service in the shared registry."""
    registry = _get_registry()
    lock = _get_lock()

    with lock:
        if record.name in registry:
            existing_data = registry[record.name]
            existing_pid = existing_data.get("pid", -1)

            if existing_pid != record.pid and _is_process_alive(existing_pid):
                raise ServiceAlreadyExists(
                    f"Service '{record.name}' is already registered by pid {existing_pid}."
                )

        registry[record.name] = record.to_dict()

def unregister_service(name: str, *, expected_pid: Optional[int] = None) -> None:
    """Remove a service from the registry."""
    registry = _get_registry()
    lock = _get_lock()

    with lock:
        if name not in registry:
            return

        if expected_pid is not None:
            existing = registry.get(name, {})
            if existing.get("pid") != expected_pid:
                return

        del registry[name]

def resolve_service(name: str) -> ServiceRecord:
    """Find a service in the registry."""
    registry = _get_registry()
    lock = _get_lock()

    with lock:
        if name not in registry:
            raise ServiceNotFound(f"Service '{name}' was not found.")

        data = registry[name]
        record = ServiceRecord.from_dict(data)

        if not _is_process_alive(record.pid):
            del registry[name]
            raise ServiceNotFound(
                f"Service '{name}' appears to be stale (process {record.pid} is not running)."
            )

        return record

def find_free_port() -> int:
    """Find an available TCP port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        port = s.getsockname()[1]
        return port