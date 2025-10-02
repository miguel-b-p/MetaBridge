"""Custom exceptions for the MetaBridge library."""

from __future__ import annotations

class MetaBridgeError(Exception):
    """Base exception for MetaBridge-related errors."""

class ServiceAlreadyExists(MetaBridgeError):
    """Raised when attempting to create a service that already exists and is active."""

class ServiceNotFound(MetaBridgeError):
    """Raised when a requested service cannot be found in the registry."""

class RemoteExecutionError(MetaBridgeError):
    """Raised when a remote call fails inside the service."""