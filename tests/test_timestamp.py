from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from sentinel.integrity.timestamp import (
    MAX_YEAR,
    MIN_YEAR,
    SYSTEM_DEFAULT_UNCERTAINTY_MS,
    SYSTEM_SUSPICIOUS_UNCERTAINTY_MS,
    Duration,
    GpsClock,
    GpsUnavailable,
    InvalidTimestampError,
    MonotonicClock,
    NtpClock,
    NtpUnavailable,
    NullTSA,
    SystemClock,
    TimeProviderError,
    TimeResolver,
    TimeResolverError,
    TimeSource,
    Timestamp,
    _check_year,
    _validate_iso_utc,
    utc_now_iso,
)


class _FakeProvider:
    """Test double for TimeProvider."""

    def __init__(self, name: str, ts: Timestamp | None, raises: Exception | None = None) -> None:
        self._name = name
        self._ts = ts
        self._raises = raises

    @property
    def name(self) -> str:
        return self._name

    def now(self) -> Timestamp:
        if self._raises is not None:
            raise self._raises
        assert self._ts is not None
        return self._ts


def _ts(
    iso: str = "2026-10-26T14:00:05Z",
    source: TimeSource = TimeSource.SYSTEM,
    uncertainty_ms: int = 100,
) -> Timestamp:
    return Timestamp(
        iso_utc=iso, source=source, uncertainty_ms=uncertainty_ms
    )


class _FakeNtpResponse:
    """Mimics the subset of ntplib.NTPStats used by NtpClock."""

    def __init__(
        self,
        offset: float = 0.0,
        delay: float = 0.010,
        root_dispersion: float = 0.005,
        stratum: int = 2,
    ) -> None:
        self.offset = offset
        self.delay = delay
        self.root_dispersion = root_dispersion
        self.stratum = stratum


class _FakeNtpClient:
    """Fake ntplib.NTPClient. Records calls, returns configured responses."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def request(self, server: str, version: int = 3, timeout: float = 2.0) -> Any:
        self.calls.append(server)
        response = self._responses.get(server)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise OSError(f"no fake response for {server}")
        return response


class TestUtcNowIso:
    def test_format(self) -> None:
        s = utc_now_iso()
        assert s.endswith("Z")
        assert "T" in s
        assert "+" not in s
        _validate_iso_utc(s)

    def test_year_in_range(self) -> None:
        year = datetime.fromisoformat(
            utc_now_iso().replace("Z", "+00:00")).year
        assert MIN_YEAR <= year <= MAX_YEAR


class TestValidateIsoUtc:
    def test_accepts_z_suffix(self) -> None:
        _validate_iso_utc("2026-10-26T14:00:05Z")

    def test_accepts_plus_zero_offset(self) -> None:
        _validate_iso_utc("2026-10-26T14:00:05+00:00")

    def test_accepts_microseconds(self) -> None:
        _validate_iso_utc("2026-10-26T14:00:05.123456Z")

    def test_rejects_empty(self) -> None:
        with pytest.raises(InvalidTimestampError, match="non-empty"):
            _validate_iso_utc("")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(InvalidTimestampError, match="non-empty"):
            _validate_iso_utc(123)

    def test_rejects_garbage(self) -> None:
        with pytest.raises(InvalidTimestampError, match="invalid ISO"):
            _validate_iso_utc("not a date")

    def test_rejects_naive(self) -> None:
        with pytest.raises(InvalidTimestampError, match="timezone-aware"):
            _validate_iso_utc("2026-10-26T14:00:05")

    def test_rejects_non_utc_offset(self) -> None:
        with pytest.raises(InvalidTimestampError, match="non-UTC offset"):
            _validate_iso_utc("2026-10-26T14:00:05-06:00")


class TestCheckYear:
    def test_ok(self) -> None:
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _check_year(dt) is None

    def test_too_early(self) -> None:
        dt = datetime(MIN_YEAR - 1, 12, 31, tzinfo=timezone.utc)
        msg = _check_year(dt)
        assert msg is not None and "before" in msg

    def test_too_late(self) -> None:
        dt = datetime(MAX_YEAR + 1, 1, 1, tzinfo=timezone.utc)
        msg = _check_year(dt)
        assert msg is not None and "after" in msg


class TestTimestamp:
    def test_basic_construction(self) -> None:
        ts = _ts()
        assert ts.iso_utc == "2026-10-26T14:00:05Z"
        assert ts.source is TimeSource.SYSTEM
        assert ts.uncertainty_ms == 100

    def test_datetime_property(self) -> None:
        ts = _ts()
        dt = ts.datetime
        assert dt.year == 2026
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)

    def test_rejects_invalid_iso(self) -> None:
        with pytest.raises(InvalidTimestampError):
            Timestamp(iso_utc="garbage", source=TimeSource.SYSTEM,
                      uncertainty_ms=100)

    def test_rejects_naive_iso(self) -> None:
        with pytest.raises(InvalidTimestampError, match="timezone-aware"):
            Timestamp(iso_utc="2026-10-26T14:00:05",
                      source=TimeSource.SYSTEM, uncertainty_ms=100)

    def test_rejects_non_utc_iso(self) -> None:
        with pytest.raises(InvalidTimestampError, match="non-UTC"):
            Timestamp(
                iso_utc="2026-10-26T14:00:05-06:00",
                source=TimeSource.SYSTEM,
                uncertainty_ms=100,
            )

    def test_rejects_non_enum_source(self) -> None:
        with pytest.raises(InvalidTimestampError, match="TimeSource"):
            Timestamp(iso_utc="2026-10-26T14:00:05Z", source="system",
                      uncertainty_ms=100)

    def test_rejects_negative_uncertainty(self) -> None:
        with pytest.raises(InvalidTimestampError, match="non-negative"):
            Timestamp(iso_utc="2026-10-26T14:00:05Z",
                      source=TimeSource.SYSTEM, uncertainty_ms=-1)

    def test_rejects_non_int_uncertainty(self) -> None:
        with pytest.raises(InvalidTimestampError, match="non-negative"):
            Timestamp(iso_utc="2026-10-26T14:00:05Z", source=TimeSource.SYSTEM,
                      uncertainty_ms=1.5)

    def test_to_dict_omits_detail_when_none(self) -> None:
        assert "provider_detail" not in _ts().to_dict()

    def test_to_dict_includes_detail(self) -> None:
        ts = Timestamp(
            iso_utc="2026-10-26T14:00:05Z",
            source=TimeSource.NTP,
            uncertainty_ms=10,
            provider_detail="ntp:pool.ntp.org stratum 2",
        )
        d = ts.to_dict()
        assert d["provider_detail"] == "ntp:pool.ntp.org stratum 2"
        assert d["source"] == "ntp"

    def test_to_manifest_fields(self) -> None:
        ts = Timestamp(
            iso_utc="2026-10-26T14:00:05Z",
            source=TimeSource.GPS,
            uncertainty_ms=5,
            provider_detail="gpsd:/dev/ttyUSB0",
        )
        f = ts.to_manifest_fields()
        assert set(f.keys()) == {"created_at",
                                 "time_source", "time_uncertainty_ms"}
        assert f["created_at"] == "2026-10-26T14:00:05Z"
        assert f["time_source"] == "gps"
        assert f["time_uncertainty_ms"] == 5


class TestSystemClock:
    def test_produces_valid_timestamp(self) -> None:
        ts = SystemClock().now()
        assert ts.source is TimeSource.SYSTEM
        assert ts.iso_utc.endswith("Z")
        assert ts.uncertainty_ms > 0

    def test_name(self) -> None:
        assert SystemClock().name == "system"

    def test_default_uncertainty_applied(self) -> None:
        ts = SystemClock(default_uncertainty_ms=42).now()
        assert ts.uncertainty_ms == 42

    def test_rejects_negative_default(self) -> None:
        with pytest.raises(ValueError):
            SystemClock(default_uncertainty_ms=-1)

    def test_flags_suspicious_year(self, monkeypatch: pytest.MonkeyPatch) -> None:

        import sentinel.integrity.timestamp as ts_mod

        real_datetime = ts_mod.datetime

        class _FrozenDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(1970, 1, 1, tzinfo=timezone.utc)

        monkeypatch.setattr(ts_mod, "datetime", _FrozenDatetime)
        ts = SystemClock().now()
        assert ts.uncertainty_ms == SYSTEM_SUSPICIOUS_UNCERTAINTY_MS
        assert ts.provider_detail is not None
        assert "before" in ts.provider_detail

    def test_normal_clock_has_default_uncertainty(self) -> None:
        ts = SystemClock().now()
        assert ts.uncertainty_ms == SYSTEM_DEFAULT_UNCERTAINTY_MS


class TestNtpClock:
    def test_rejects_empty_servers(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            NtpClock(servers=[])

    def test_raises_when_no_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sentinel.integrity.timestamp as ts_mod

        monkeypatch.setattr(ts_mod, "_NTP_AVAILABLE", False)
        clock = NtpClock()
        with pytest.raises(NtpUnavailable, match="ntplib is not installed"):
            clock.now()

    def test_uses_first_healthy_server(self) -> None:
        response = _FakeNtpResponse(
            offset=0.050, delay=0.020, root_dispersion=0.005, stratum=2)
        client = _FakeNtpClient(
            {"a.ntp": OSError("timeout"), "b.ntp": response, "c.ntp": response}
        )
        ts = NtpClock(servers=["a.ntp", "b.ntp", "c.ntp"], client=client).now()
        assert ts.source is TimeSource.NTP
        assert "b.ntp" in (ts.provider_detail or "") or "c.ntp" in (
            ts.provider_detail or "")
        assert ts.uncertainty_ms >= 1

    def test_picks_lowest_uncertainty(self) -> None:
        resp_b = _FakeNtpResponse(
            offset=0.0, delay=0.005, root_dispersion=0.001, stratum=1)
        resp_c = _FakeNtpResponse(
            offset=0.0, delay=0.050, root_dispersion=0.100, stratum=3)
        client = _FakeNtpClient({"b.ntp": resp_b, "c.ntp": resp_c})
        ts = NtpClock(servers=["b.ntp", "c.ntp"], client=client).now()
        assert "b.ntp" in (ts.provider_detail or "")

    def test_all_servers_fail(self) -> None:
        client = _FakeNtpClient({"a": OSError("x"), "b": OSError("y")})
        with pytest.raises(NtpUnavailable, match="all NTP servers failed"):
            NtpClock(servers=["a", "b"], client=client).now()

    def test_offset_applied_to_local_clock(self) -> None:
        before = datetime.now(timezone.utc)
        response = _FakeNtpResponse(
            offset=10.0, delay=0.010, root_dispersion=0.001)
        ts = NtpClock(servers=["x"], client=_FakeNtpClient(
            {"x": response})).now()
        after = datetime.now(timezone.utc)
        parsed = ts.datetime
        assert before + \
            timedelta(seconds=10) <= parsed <= after + timedelta(seconds=11)

    def test_uncertainty_is_at_least_one_ms(self) -> None:
        response = _FakeNtpResponse(offset=0.0, delay=0.0, root_dispersion=0.0)
        ts = NtpClock(servers=["x"], client=_FakeNtpClient(
            {"x": response})).now()
        assert ts.uncertainty_ms >= 1

    def test_flags_suspicious_year_from_ntp(self) -> None:
        far_past_offset_s = (
            datetime(1970, 1, 1, tzinfo=timezone.utc)
            - datetime.now(timezone.utc)
        ).total_seconds()
        response = _FakeNtpResponse(offset=far_past_offset_s)
        ts = NtpClock(servers=["x"], client=_FakeNtpClient(
            {"x": response})).now()
        assert ts.uncertainty_ms >= SYSTEM_SUSPICIOUS_UNCERTAINTY_MS
        assert ts.provider_detail is not None
        assert "before" in ts.provider_detail


class TestGpsClock:
    def test_name(self) -> None:
        assert GpsClock().name == "gps"

    def test_stub_raises(self) -> None:
        with pytest.raises(GpsUnavailable, match="not configured"):
            GpsClock().now()

    def test_accepts_implementation(self) -> None:
        class _Impl:
            def now(self) -> Timestamp:
                return _ts(source=TimeSource.GPS, uncertainty_ms=1)

        ts = GpsClock(implementation=_Impl()).now()
        assert ts.source is TimeSource.GPS

    def test_rejects_wrong_source_from_implementation(self) -> None:
        class _Impl:
            def now(self) -> Timestamp:
                return _ts(source=TimeSource.SYSTEM)

        with pytest.raises(TimeProviderError, match="expected 'gps'"):
            GpsClock(implementation=_Impl()).now()


class TestTimeResolver:
    def test_falls_through_to_next_provider(self) -> None:
        good = _ts(source=TimeSource.SYSTEM)
        resolver = TimeResolver(
            providers=[
                _FakeProvider("gps", ts=None, raises=GpsUnavailable("no gps")),
                _FakeProvider("ntp", ts=None, raises=NtpUnavailable("no ntp")),
                _FakeProvider("system", ts=good),
            ]
        )
        assert resolver.now() is good

    def test_returns_first_success(self) -> None:
        gps = _ts(source=TimeSource.GPS, uncertainty_ms=1)
        sys = _ts(source=TimeSource.SYSTEM)
        resolver = TimeResolver(
            providers=[
                _FakeProvider("gps", ts=gps),
                _FakeProvider("system", ts=sys),
            ]
        )
        assert resolver.now() is gps

    def test_all_fail_raises(self) -> None:
        resolver = TimeResolver(
            providers=[
                _FakeProvider("gps", ts=None, raises=GpsUnavailable("x")),
                _FakeProvider("ntp", ts=None, raises=NtpUnavailable("y")),
            ]
        )
        with pytest.raises(TimeResolverError, match="no time source available"):
            resolver.now()

    def test_require_source_matches(self) -> None:
        gps = _ts(source=TimeSource.GPS)
        resolver = TimeResolver(providers=[_FakeProvider("gps", ts=gps)])
        assert resolver.now(require_source=TimeSource.GPS) is gps

    def test_require_source_skips_mismatch(self) -> None:
        sys = _ts(source=TimeSource.SYSTEM)
        resolver = TimeResolver(providers=[_FakeProvider("system", ts=sys)])
        with pytest.raises(TimeResolverError, match="require_source"):
            resolver.now(require_source=TimeSource.GPS)

    def test_rejects_empty_providers(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            TimeResolver(providers=[])

    def test_providers_property(self) -> None:
        resolver = TimeResolver(
            providers=[
                _FakeProvider("gps", ts=_ts(source=TimeSource.GPS)),
                _FakeProvider("system", ts=_ts()),
            ]
        )
        assert resolver.providers == ("gps", "system")

    def test_default_providers_include_gps_ntp_system(self) -> None:
        resolver = TimeResolver()
        assert resolver.providers == ("gps", "ntp", "system")

    def test_default_resolver_returns_system_when_gps_ntp_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sentinel.integrity.timestamp as ts_mod

        monkeypatch.setattr(ts_mod, "_NTP_AVAILABLE", False)
        ts = TimeResolver().now()
        assert ts.source is TimeSource.SYSTEM


class TestMonotonicClock:
    def test_measures_elapsed_time(self) -> None:
        mc = MonotonicClock()
        mc.start()
        total = sum(range(1000))
        duration = mc.stop()
        assert duration.elapsed_ns >= 0
        assert duration.elapsed_ms >= 0.0
        assert total == sum(range(1000))

    def test_stop_before_start_raises(self) -> None:
        with pytest.raises(RuntimeError, match="before start"):
            MonotonicClock().stop()

    def test_restart_resets(self) -> None:
        mc = MonotonicClock()
        mc.start()
        d1 = mc.stop()
        mc.start()
        d2 = mc.stop()
        assert d1.elapsed_ns >= 0
        assert d2.elapsed_ns >= 0

    def test_monotonic_source_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sentinel.integrity.timestamp as ts_mod

        readings = iter([1_000_000_000, 2_500_000_000])
        monkeypatch.setattr(ts_mod, "_monotonic_ns", lambda: next(readings))
        mc = MonotonicClock()
        mc.start()
        d = mc.stop()
        assert d.elapsed_ns == 1_500_000_000
        assert d.elapsed_s == 1.5
        assert d.elapsed_ms == 1500.0


class TestDuration:
    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            Duration(elapsed_ns=-1)

    def test_unit_conversions(self) -> None:
        d = Duration(elapsed_ns=2_500_000_000)
        assert d.elapsed_ms == 2500.0
        assert d.elapsed_s == 2.5

    def test_to_dict(self) -> None:
        d = Duration(elapsed_ns=1_000_000_000)
        assert d.to_dict() == {"elapsed_ns": 1_000_000_000, "elapsed_s": 1.0}


class TestNullTSA:
    def test_returns_none(self) -> None:
        assert NullTSA().timestamp("a" * 64) is None
