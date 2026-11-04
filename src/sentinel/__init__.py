"""Sentinel-Anubis OS — forensic subsystem."""

__version__ = "0.1.0"


class SentinelError(Exception):
    """Base class for all Sentinel forensic-subsystem errors."""


class SentinelCustodyError(SentinelError):
    """Base class for chain-of-custody errors."""


class SentinelPackagingError(SentinelError):
    """Base class for `.sae` packaging errors."""
