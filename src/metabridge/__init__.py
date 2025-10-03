# src/metabridge/__init__.py
"""MetaBridge - High-performance in-memory service pipes for intra-project function calls."""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional, overload

from .client import ServiceClient, connect_service
from .exceptions import (
    MetaBridgeError,
    RemoteExecutionError,
    ServiceAlreadyExists,
    ServiceNotFound,
)
from .server import DaemonHandle, DaemonServiceBuilder, ServiceBuilder, create_service

__all__ = [
    "MetaBridgeError",
    "RemoteExecutionError",
    "ServiceAlreadyExists",
    "ServiceNotFound",
    "ServiceBuilder",
    "DaemonHandle",
    "ServiceClient",
    "create",
    "run",
    "connect",
    "endpoint",
    "function", # Adicionado para clareza
]


def _mark_endpoint(func: Callable[..., Any], alias: Optional[str]) -> Callable[..., Any]:
    """Internal helper to attach metadata to a function."""
    # Se alias for None, o nome do endpoint será o nome da função.
    # Se for uma string, será o alias.
    setattr(func, "metabridge_endpoint", alias)
    return func

# Sobrecargas para melhor suporte a tipos e autocompletar no editor.
@overload
def endpoint(func: Callable[..., Any]) -> Callable[..., Any]: ...
@overload
def endpoint(*, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

def endpoint(
    func: Optional[Callable[..., Any]] = None, *, name: Optional[str] = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]] | Callable[..., Any]:
    """
    Marks a method as a remotely accessible endpoint.

    Can be used as `@meta.endpoint` or `@meta.endpoint(name="custom_name")`.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        return _mark_endpoint(fn, name or fn.__name__)

    return decorator(func) if func else decorator


def function(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to expose a function as an endpoint using its own name.
    Shorthand for `@meta.endpoint`.
    """
    return _mark_endpoint(func, func.__name__)


def __getattr__(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Provides dynamic decorators for endpoints (e.g., @meta.get, @meta.test).
    The attribute name becomes the endpoint name.
    """
    if name.startswith("_") or name in __all__:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return _mark_endpoint(func, name)

    return decorator


class _ServiceRegistration:
    """Holds metadata about a declared MetaBridge service."""

    def __init__(self, name: str, host: Optional[str] = None) -> None:
        self.name = name
        self._builder = create_service(name, host=host)
        self._daemon_builder: Optional[DaemonServiceBuilder] = None
        self._class: Optional[type] = None
        self._seen_endpoints: set[str] = set()

    def daemon(self) -> "_ServiceClassDecorator":
        if self._daemon_builder is None:
            self._daemon_builder = self._builder.daemon()
        return _ServiceClassDecorator(self)

    def _ensure_daemon_builder(self) -> DaemonServiceBuilder:
        if self._daemon_builder is None:
            self._daemon_builder = self._builder.daemon()
        return self._daemon_builder

    def _register_class(self, cls: type) -> type:
        self._class = cls
        self._seen_endpoints.clear()
        builder = self._ensure_daemon_builder()

        for attr_name, member in cls.__dict__.items():
            func, descriptor = _extract_callable(member)
            if func is None or not hasattr(func, "metabridge_endpoint"):
                continue

            endpoint_name = getattr(func, "metabridge_endpoint")
            _annotate_endpoint(func, cls, attr_name, descriptor)

            # O nome do endpoint é o alias ou o nome da função.
            # Também registramos o nome do atributo como um alias implícito.
            names_to_register = {endpoint_name, attr_name}

            for endpoint in names_to_register:
                if endpoint in self._seen_endpoints:
                    continue
                builder._register_endpoint(endpoint, func)
                self._seen_endpoints.add(endpoint)
        return cls

    def run(
        self,
        *,
        wait: bool = False,
        poll_interval: float = 0.5,
        startup_timeout: float = 5.0,
    ) -> DaemonHandle:
        builder = self._ensure_daemon_builder()
        return builder.run(wait=wait, poll_interval=poll_interval, startup_timeout=startup_timeout)


class _ServiceClassDecorator:
    def __init__(self, registration: _ServiceRegistration) -> None:
        self._registration = registration

    def __call__(self, cls: type) -> type:
        return self._registration._register_class(cls)


def _extract_callable(member: Any) -> tuple[Optional[Callable[..., Any]], str]:
    if isinstance(member, staticmethod):
        return member.__func__, "staticmethod"
    if isinstance(member, classmethod):
        return member.__func__, "classmethod"
    if inspect.isfunction(member):
        return member, "instance"
    return None, ""


def _annotate_endpoint(func: Callable[..., Any], owner: type, attr_name: str, descriptor: str) -> None:
    setattr(func, "metabridge_owner", owner)
    setattr(func, "metabridge_attr", attr_name)
    setattr(func, "metabridge_descriptor", descriptor)


_SERVICE_REGISTRY: Dict[str, _ServiceRegistration] = {}
_LAST_REGISTRATION: Optional[_ServiceRegistration] = None


def create(name: str, host: Optional[str] = None) -> _ServiceRegistration:
    """Create (or retrieve) a MetaBridge service registration for the given name."""
    registration = _SERVICE_REGISTRY.get(name)
    if registration is None:
        registration = _ServiceRegistration(name, host=host)
        _SERVICE_REGISTRY[name] = registration
    global _LAST_REGISTRATION
    _LAST_REGISTRATION = registration
    return registration


def _resolve_registration(name: Optional[str]) -> _ServiceRegistration:
    if name is not None:
        try:
            return _SERVICE_REGISTRY[name]
        except KeyError as exc:
            raise MetaBridgeError(f"Service '{name}' was not registered via metabridge.create().") from exc
    if _LAST_REGISTRATION is None:
        raise MetaBridgeError("No MetaBridge service has been registered yet.")
    return _LAST_REGISTRATION


def run(
    name: Optional[str] = None,
    *,
    wait: bool = False,
    poll_interval: float = 0.5,
    startup_timeout: float = 5.0,
) -> DaemonHandle:
    """Launch the given service in daemon mode."""
    registration = _resolve_registration(name)
    return registration.run(wait=wait, poll_interval=poll_interval, startup_timeout=startup_timeout)


def connect(
    name: str,
    *ctor_args: Any,
    timeout: float = 5.0,
    poll_interval: float = 0.002,
    **ctor_kwargs: Any,
) -> ServiceClient:
    """Connect to a MetaBridge service."""
    return connect_service(
        name,
        *ctor_args,
        timeout=timeout,
        poll_interval=poll_interval,
        **ctor_kwargs,
    )