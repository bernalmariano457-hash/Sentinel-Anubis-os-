from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from sentinel import SentinelError

logger = logging.getLogger(__name__)

try:
    import ntplib

    _NTP_AVAILABLE = True
except ImportError:
    ntplib = None
    _NTP_AVAILABLE = False

MIN_YEAR: int = 2024
MAX_YEAR: int = 2100

SYSTEM_DEFAULT_UNCERTAINTY_MS: int = 1_000

SYSTEM_SUSPICIOUS_UNCERTAINTY_MS: int = 86_400_000

DEFAULT_NTP_SERVERS: tuple[str, ...] = (
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
)


class TimestampError(SentinelError):
    """Base class for all timestamp-related errors."""


class TimeProviderError(TimestampError):
    """A specific time provider failed or is unavailable."""


class GpsUnavailable(TimeProviderError):
    """No GPS device present, not locked, or not configured."""


class NtpUnavailable(TimeProviderError):
    """ntplib not installed or all NTP servers failed."""


class TimeResolverError(TimestampError):
    """No time source could produce a timestamp."""


class InvalidTimestampError(TimestampError):
    """A timestamp string or field is malformed or out of range."""
class TimeSource(StrEnum):

    GPS = "gps"
    NTP = "ntp"
    SYSTEM = "system"


@dataclass(frozen=True)
class Timestamp:

    iso_utc: str
    source: TimeSource
    uncertainty_ms: int
    provider_detail: str | None = None

    def __post_init__(self) -> None:
        _validate_iso_utc(self.iso_utc)
        if not isinstance(self.source, TimeSource):
            raise InvalidTimestampError(
                f"source must be a TimeSource, got {type(self.source).__name__}"
            )
        if not isinstance(self.uncertainty_ms, int) or self.uncertainty_ms < 0:
            raise InvalidTimestampError(
                f"uncertainty_ms must be a non-negative int, got {self.uncertainty_ms!r}"
            )

    @property
    def datetime(self) -> datetime:
        return datetime.fromisoformat(self.iso_utc.replace("Z", "+00:00"))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "iso_utc": self.iso_utc,
            "source": self.source.value,
            "uncertainty_ms": self.uncertainty_ms,
        }
        if self.provider_detail:
            d["provider_detail"] = self.provider_detail
        return d

    def to_manifest_fields(self) -> dict[str, str | int]:
        return {
            "created_at": self.iso_utc,
            "time_source": self.source.value,
            "time_uncertainty_ms": self.uncertainty_ms,
        }


@dataclass(frozen=True)
class Duration:

    elapsed_ns: int

    def __post_init__(self) -> None:
        if self.elapsed_ns < 0:
            raise ValueError(
                f"elapsed_ns must be non-negative, got {self.elapsed_ns}")

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed_ns / 1_000_000

    @property
    def elapsed_s(self) -> float:
        return self.elapsed_ns / 1_000_000_000

    def to_dict(self) -> dict[str, float | int]:
        return {"elapsed_ns": self.elapsed_ns, "elapsed_s": self.elapsed_s}


@runtime_checkable
class TimeProvider(Protocol):

    @property
    def name(self) -> str:
        ...

    def now(self) -> Timestamp:
        ...


def utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _validate_iso_utc(s: str) -> datetime:

    if not isinstance(s, str) or not s:
        raise InvalidTimestampError(
            f"timestamp must be a non-empty string, got {s!r}")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise InvalidTimestampError(
            f"invalid ISO 8601 timestamp {s!r}: {e}") from e
    if dt.tzinfo is None:
        raise InvalidTimestampError(f"timestamp {s!r} is not timezone-aware")
    if dt.utcoffset() != timedelta(0):
        raise InvalidTimestampError(
            f"timestamp {s!r} has non-UTC offset {dt.utcoffset()}"
        )
    return dt


def _check_year(dt: datetime) -> str | None:
    if dt.year < MIN_YEAR:
        return f"year {dt.year} is before {MIN_YEAR}; clock is likely wrong"
    if dt.year > MAX_YEAR:
        return f"year {dt.year} is after {MAX_YEAR}; clock is likely wrong"
    return None


def _iso_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class SystemClock:

    def __init__(
        self,
        default_uncertainty_ms: int = SYSTEM_DEFAULT_UNCERTAINTY_MS,
    ) -> None:
        if default_uncertainty_ms < 0:
            raise ValueError("default_uncertainty_ms must be non-negative")
        self._default_uncertainty_ms = default_uncertainty_ms

    @property
    def name(self) -> str:
        return "system"

    def now(self) -> Timestamp:
        now = datetime.now(UTC)
        warning = _check_year(now)
        if warning is not None:
            return Timestamp(
                iso_utc=_iso_from_datetime(now),
                source=TimeSource.SYSTEM,
                uncertainty_ms=SYSTEM_SUSPICIOUS_UNCERTAINTY_MS,
                provider_detail=warning,
            )
        return Timestamp(
            iso_utc=_iso_from_datetime(now),
            source=TimeSource.SYSTEM,
            uncertainty_ms=self._default_uncertainty_ms,
            provider_detail="system clock; NTP sync status unknown",
        )


class NtpClock:

    def __init__(
        self,
        servers: Sequence[str] | None = None,
        timeout_s: float = 2.0,
        client: Any | None = None,
    ) -> None:
        self.servers: tuple[str, ...] = tuple(
            servers) if servers else DEFAULT_NTP_SERVERS
        if not self.servers:
            raise ValueError("servers must be non-empty")
        self.timeout_s = timeout_s
        self._client: Any = client

    @property
    def name(self) -> str:
        return "ntp"

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not _NTP_AVAILABLE:
            raise NtpUnavailable(
                "ntplib is not installed; install with 'pip install ntplib' "
                "or rely on SystemClock/GpsClock"
            )
        client = ntplib.NTPClient()
        self._client = client
        return client

    def now(self) -> Timestamp:
        client = self._get_client()
        results: list[dict[str, Any]] = []
        errors: list[tuple[str, str]] = []

        for server in self.servers:
            try:
                response = client.request(
                    server, version=3, timeout=self.timeout_s)
            except Exception as e:  # ntplib raises several unrelated types
                errors.append((server, str(e)))
                logger.debug("NTP query to %s failed: %s", server, e)
                continue

            offset_ms = float(response.offset) * 1000.0
            uncertainty_ms = (
                float(response.root_dispersion) + float(response.delay) / 2.0
            ) * 1000.0
            results.append(
                {
                    "server": server,
                    "offset_ms": offset_ms,
                    "uncertainty_ms": uncertainty_ms,
                    "stratum": int(getattr(response, "stratum", 0)),
                }
            )

        if not results:
            raise NtpUnavailable(
                f"all NTP servers failed: {[f'{s}: {e}' for s, e in errors]}"
            )

        best = min(results, key=lambda r: r["uncertainty_ms"])
        now = datetime.now(UTC) + \
            timedelta(milliseconds=best["offset_ms"])
        warning = _check_year(now)
        uncertainty = max(1, round(best["uncertainty_ms"]))
        detail = f"ntp:{best['server']} stratum {best['stratum']}"

        if warning is not None:

            return Timestamp(
                iso_utc=_iso_from_datetime(now),
                source=TimeSource.NTP,
                uncertainty_ms=max(
                    uncertainty, SYSTEM_SUSPICIOUS_UNCERTAINTY_MS),
                provider_detail=f"{detail}; {warning}",
            )

        return Timestamp(
            iso_utc=_iso_from_datetime(now),
            source=TimeSource.NTP,
            uncertainty_ms=uncertainty,
            provider_detail=detail,
        )


@runtime_checkable
class GpsImplementation(Protocol):

    def now(self) -> Timestamp:
        ...


class GpsClock:

    def __init__(self, implementation: GpsImplementation | None = None) -> None:
        self._impl = implementation

    @property
    def name(self) -> str:
        return "gps"

    def now(self) -> Timestamp:
        if self._impl is None:
            raise GpsUnavailable(
                "GPS provider not configured (Fase 1 stub); "
                "see docs/forensics/methods/gps.md"
            )
        ts = self._impl.now()
        if ts.source != TimeSource.GPS:
            raise TimeProviderError(
                f"GpsImplementation returned source {ts.source.value!r}, "
                "expected 'gps'"
            )
        return ts


class TimeResolver:

    def __init__(self, providers: Sequence[TimeProvider] | None = None) -> None:
        if providers is None:
            providers = (GpsClock(), NtpClock(), SystemClock())
        if not providers:
            raise ValueError("providers must be non-empty")
        self._providers: tuple[TimeProvider, ...] = tuple(providers)

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(p.name for p in self._providers)

    def now(self, *, require_source: TimeSource | None = None) -> Timestamp:

        last_error: Exception | None = None
        for provider in self._providers:
            try:
                ts = provider.now()
            except TimeProviderError as e:
                logger.debug("time provider %s unavailable: %s",
                             provider.name, e)
                last_error = e
                continue
            if require_source is not None and ts.source != require_source:
                logger.debug(
                    "time provider %s returned source %s, need %s; skipping",
                    provider.name,
                    ts.source.value, require_source.value,
                )
                last_error = TimeResolverError(
                    f"provider {provider.name!r} returned {ts.source.value!r}, "
                    f"require_source={require_source.value!r}"
                )
                continue
            return ts
        msg = "no time source available"
        if require_source is not None:
            msg += f" with require_source={require_source.value!r}"
        raise TimeResolverError(msg) from last_error


class MonotonicClock:

    def __init__(self) -> None:
        self._start_ns: int | None = None

    def start(self) -> None:
        self._start_ns = _monotonic_ns()

    def stop(self) -> Duration:
        if self._start_ns is None:
            raise RuntimeError("MonotonicClock.stop() called before start()")
        return Duration(elapsed_ns=_monotonic_ns() - self._start_ns)


def _monotonic_ns() -> int:
    import time as _time

    return _time.monotonic_ns()


@runtime_checkable
class TimestampAuthority(Protocol):

    def timestamp(self, digest_hex: str) -> str | None:
        ...


class NullTSA:

    def timestamp(self, digest_hex: str) -> str | None:
        return None


__all__ = [
    "DEFAULT_NTP_SERVERS",
    "MAX_YEAR",
    "MIN_YEAR",
    "SYSTEM_DEFAULT_UNCERTAINTY_MS",
    "SYSTEM_SUSPICIOUS_UNCERTAINTY_MS",
    "Duration",
    "GpsClock",
    "GpsImplementation",
    "GpsUnavailable",
    "InvalidTimestampError",
    "MonotonicClock",
    "NtpClock",
    "NtpUnavailable",
    "NullTSA",
    "SystemClock",
    "TimeProvider",
    "TimeProviderError",
    "TimeResolver",
    "TimeResolverError",
    "TimeSource",
    "Timestamp",
    "TimestampAuthority",
    "TimestampError",
    "utc_now_iso",
]
