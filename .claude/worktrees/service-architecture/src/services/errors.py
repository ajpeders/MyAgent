"""Base error class for all service exceptions."""


class ServiceError(Exception):
    """Base class for service errors. Caught by gateway and mapped to HTTP 502."""

    pass