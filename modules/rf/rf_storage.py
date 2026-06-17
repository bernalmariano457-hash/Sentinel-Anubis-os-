from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BufferedWriter
from pathlib import Path
from typing import Any, Generator, Protocol, runtime_checkable

import numpy as np

from modules.rf.rf_config import StorageConfig

log = logging.getLogger(__name__)

_SCHEMA_SQL: str = (
    "PRAGMA journal_mode = WAL;\n"
    "PRAGMA foreign_keys = ON;\n"
    "PRAGMA cache_size = -8000;\n"
    "\n"
    "CREATE TABLE IF NOT EXISTS sessions (\n"
    "    id          INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    started_at  TEXT    NOT NULL,\n"
    "    ended_at    TEXT,\n"
    "    hw_type     TEXT,\n"
    "    sample_rate INTEGER,\n"
    "    notes       TEXT\n"
    ");\n"
    "\n"
    "CREATE TABLE IF NOT EXISTS signals (\n"
    "    id          INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,\n"
    "    timestamp   TEXT    NOT NULL,\n"
    "    freq_mhz    REAL    NOT NULL,\n"
    "    potencia    REAL    NOT NULL,\n"
    "    snr_db      REAL    NOT NULL,\n"
    "    bw_khz      REAL    NOT NULL,\n"
    "    piso_dbm    REAL    NOT NULL,\n"
    "    kurtosis    REAL    DEFAULT 0.0,\n"
    "    mod_hint    TEXT,\n"
    "    banda       TEXT,\n"
    "    banda_tipo  TEXT,\n"
    "    tactica     INTEGER DEFAULT 0\n"
    ");\n"
    "\n"
    "CREATE TABLE IF NOT EXISTS sweeps (\n"
    "    id          INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,\n"
    "    timestamp   TEXT    NOT NULL,\n"
    "    freq_ini    REAL    NOT NULL,\n"
    "    freq_fin    REAL    NOT NULL,\n"
    "    paso_mhz    REAL    NOT NULL,\n"
    "    puntos      INTEGER NOT NULL,\n"
    "    activas     INTEGER NOT NULL\n"
    ");\n"
    "\n"
    "CREATE TABLE IF NOT EXISTS iq_recordings (\n"
    "    id          INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,\n"
    "    timestamp   TEXT    NOT NULL,\n"
    "    freq_mhz    REAL    NOT NULL,\n"
    "    duration_s  REAL    NOT NULL,\n"
    "    sample_rate INTEGER NOT NULL,\n"
    "    hw_type     TEXT,\n"
    "    filename    TEXT    NOT NULL,\n"
    "    size_mb     REAL,\n"
    "    notes       TEXT\n"
    ");\n"
    "\n"
    "CREATE INDEX IF NOT EXISTS idx_signals_freq      ON signals(freq_mhz);\n"
    "CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);\n"
    "CREATE INDEX IF NOT EXISTS idx_signals_session   ON signals(session_id);\n"
    "CREATE INDEX IF NOT EXISTS idx_signals_snr       ON signals(snr_db DESC);\n"
)

_INSERT_SIGNAL_SQL: str = (
    "INSERT INTO signals "
    "(session_id, timestamp, freq_mhz, potencia, snr_db, "
    "bw_khz, piso_dbm, kurtosis, mod_hint, banda, banda_tipo, tactica) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_PRAGMA_BLOCK: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA cache_size=-8000",
)

_SIGNAL_CSV_FIELDS: tuple[str, ...] = (
    "timestamp", "freq_mhz", "potencia", "snr_db",
    "bw_khz", "piso_dbm", "kurtosis", "mod_hint", "banda",
)

_SWEEP_CSV_FIELDS: tuple[str, ...] = (
    "freq_mhz", "pot_max", "piso", "snr", "banda",
)

_SIGMF_VERSION: str  = "1.0.0"
_SIGMF_DATATYPE: str = "cf32_le"


@runtime_checkable
class _SignalLike(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signal_to_dict(signal: Any) -> dict[str, Any]:
    if isinstance(signal, _SignalLike):
        return signal.to_dict()
    return dict(signal)


def _extract_banda_fields(signal: Any) -> tuple[str, str, int]:
    banda_obj = getattr(signal, "banda", None)
    if not banda_obj:
        return ("", "", 0)
    return (
        banda_obj.get("nombre", ""),
        banda_obj.get("tipo", ""),
        1 if banda_obj.get("peligro", False) else 0,
    )


def _signal_to_row(
    signal: Any,
    session_id: int | None,
    fallback_timestamp: str,
) -> tuple:
    d = _signal_to_dict(signal)
    banda_nombre, banda_tipo, tactica = _extract_banda_fields(signal)
    return (
        session_id,
        d.get("timestamp", fallback_timestamp),
        d["freq_mhz"],
        d["potencia"],
        d["snr_db"],
        d["bw_khz"],
        d["piso_dbm"],
        d.get("kurtosis", 0.0),
        d.get("mod_hint", ""),
        banda_nombre,
        banda_tipo,
        tactica,
    )


def _open_thread_local_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=True,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMA_BLOCK:
        conn.execute(pragma)
    return conn


class SignalDB:

    def __init__(self, cfg: StorageConfig) -> None:
        self._db_path: Path = cfg.db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock: threading.Lock = threading.Lock()
        self._local: threading.local = threading.local()
        self._session_id: int | None = None
        self._session_lock: threading.Lock = threading.Lock()
        self._bootstrap_schema()
        log.debug("SignalDB initialised at %s", self._db_path)

    def _bootstrap_schema(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def _thread_conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = _open_thread_local_connection(self._db_path)
            self._local.conn = conn
        return conn

    @contextmanager
    def _write_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        for pragma in _PRAGMA_BLOCK:
            conn.execute(pragma)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @property
    def current_session_id(self) -> int | None:
        with self._session_lock:
            return self._session_id

    def open_session(
        self,
        hw_type: str = "",
        sample_rate: int = 0,
        notes: str = "",
    ) -> int:
        started_at = _utc_now_iso()
        with self._write_lock, self._write_conn() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at, hw_type, sample_rate, notes) "
                "VALUES (?, ?, ?, ?)",
                (started_at, hw_type, sample_rate, notes),
            )
            new_id: int = cur.lastrowid
        with self._session_lock:
            self._session_id = new_id
        log.info("RF session opened — ID=%d", new_id)
        return new_id

    def close_session(self) -> None:
        with self._session_lock:
            session_id = self._session_id
        if session_id is None:
            return
        ended_at = _utc_now_iso()
        with self._write_lock, self._write_conn() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at=? WHERE id=?",
                (ended_at, session_id),
            )
        with self._session_lock:
            self._session_id = None
        log.info("RF session closed — ID=%d", session_id)

    def insert_signal(self, signal: Any) -> int:
        fallback_ts = _utc_now_iso()
        row = _signal_to_row(signal, self.current_session_id, fallback_ts)
        with self._write_lock, self._write_conn() as conn:
            cur = conn.execute(_INSERT_SIGNAL_SQL, row)
            return cur.lastrowid

    def insert_signals_batch(self, signals: list[Any]) -> int:
        if not signals:
            return 0
        batch_timestamp = _utc_now_iso()
        session_id = self.current_session_id
        rows = [
            _signal_to_row(signal, session_id, batch_timestamp)
            for signal in signals
        ]
        with self._write_lock, self._write_conn() as conn:
            conn.executemany(_INSERT_SIGNAL_SQL, rows)
        return len(rows)

    def get_signals(
        self,
        session_id: int | None = None,
        freq_min: float = 0.0,
        freq_max: float = 99_999.0,
        snr_min: float = 0.0,
        limit: int = 1_000,
    ) -> list[dict[str, Any]]:
        resolved_session = session_id or self.current_session_id
        conn = self._thread_conn()

        if resolved_session is not None:
            cur = conn.execute(
                "SELECT * FROM signals "
                "WHERE session_id=? "
                "AND freq_mhz BETWEEN ? AND ? "
                "AND snr_db >= ? "
                "ORDER BY snr_db DESC LIMIT ?",
                (resolved_session, freq_min, freq_max, snr_min, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM signals "
                "WHERE freq_mhz BETWEEN ? AND ? "
                "AND snr_db >= ? "
                "ORDER BY snr_db DESC LIMIT ?",
                (freq_min, freq_max, snr_min, limit),
            )
        return [dict(row) for row in cur.fetchall()]

    def insert_sweep(
        self,
        freq_ini: float,
        freq_fin: float,
        paso: float,
        puntos: int,
        activas: int,
    ) -> None:
        ts = _utc_now_iso()
        with self._write_lock, self._write_conn() as conn:
            conn.execute(
                "INSERT INTO sweeps "
                "(session_id, timestamp, freq_ini, freq_fin, paso_mhz, puntos, activas) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.current_session_id, ts, freq_ini, freq_fin, paso, puntos, activas),
            )

    def register_iq(
        self,
        freq_mhz: float,
        duration_s: float,
        sample_rate: int,
        hw_type: str,
        filename: str,
        size_mb: float,
        notes: str = "",
    ) -> None:
        ts = _utc_now_iso()
        with self._write_lock, self._write_conn() as conn:
            conn.execute(
                "INSERT INTO iq_recordings "
                "(session_id, timestamp, freq_mhz, duration_s, sample_rate, "
                "hw_type, filename, size_mb, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.current_session_id, ts, freq_mhz, duration_s,
                    sample_rate, hw_type, filename, size_mb, notes,
                ),
            )

    def purge_old(self, retention_days: int) -> None:
        if retention_days <= 0:
            return
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        with self._write_lock, self._write_conn() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE started_at < ?", (cutoff,)
            )
        log.info("RF records older than %s purged", cutoff)

    def stats(self) -> dict[str, Any]:
        conn = self._thread_conn()
        counts: dict[str, int] = {}
        for table in ("sessions", "signals", "sweeps", "iq_recordings"):
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        db_size_mb = (
            round(self._db_path.stat().st_size / 1e6, 2)
            if self._db_path.exists()
            else 0.0
        )
        return {
            "sessions":   counts["sessions"],
            "signals":    counts["signals"],
            "sweeps":     counts["sweeps"],
            "iq_files":   counts["iq_recordings"],
            "db_size_mb": db_size_mb,
        }


def _build_signal_csv_row(signal: Any) -> dict[str, Any]:
    d = _signal_to_dict(signal)
    return {
        "timestamp": d.get("timestamp", ""),
        "freq_mhz":  d.get("freq_mhz",  ""),
        "potencia":  d.get("potencia",  ""),
        "snr_db":    d.get("snr_db",    ""),
        "bw_khz":    d.get("bw_khz",    ""),
        "piso_dbm":  d.get("piso_dbm",  ""),
        "kurtosis":  d.get("kurtosis",  ""),
        "mod_hint":  d.get("mod_hint",  ""),
        "banda":     d.get("banda",     ""),
    }


def _build_sweep_csv_row(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "freq_mhz": result.get("freq_mhz", ""),
        "pot_max":  result.get("pot_max",  ""),
        "piso":     result.get("piso",     ""),
        "snr":      result.get("snr",      ""),
        "banda":    result["banda"]["nombre"] if result.get("banda") else "",
    }


class CSVExporter:

    def __init__(self, cfg: StorageConfig) -> None:
        self._csv_path: Path = cfg.csv_path
        self._csv_path.mkdir(parents=True, exist_ok=True)

    def export_signals(
        self,
        signals: list[Any],
        freq_mhz: float,
        hw_type: str = "",
    ) -> Path:
        ts     = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        hw_tag = hw_type.replace(" ", "_") if hw_type else "unknown"
        target = self._csv_path / f"scan_{freq_mhz:.3f}MHz_{hw_tag}_{ts}.csv"
        try:
            with open(target, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=_SIGNAL_CSV_FIELDS)
                writer.writeheader()
                writer.writerows(_build_signal_csv_row(s) for s in signals)
        except OSError as exc:
            log.error("CSV signal export failed: %s", exc)
            raise
        log.info("CSV signals -> %s", target)
        return target

    def export_sweep(
        self,
        results: list[dict[str, Any]],
        freq_ini: float,
        freq_fin: float,
    ) -> Path:
        ts     = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = self._csv_path / f"sweep_{freq_ini:.0f}-{freq_fin:.0f}MHz_{ts}.csv"
        try:
            with open(target, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=_SWEEP_CSV_FIELDS)
                writer.writeheader()
                writer.writerows(_build_sweep_csv_row(r) for r in results)
        except OSError as exc:
            log.error("CSV sweep export failed: %s", exc)
            raise
        log.info("CSV sweep -> %s", target)
        return target


class SigMFWriter:

    def __init__(self, cfg: StorageConfig) -> None:
        self._iq_path: Path = cfg.iq_path
        self._iq_path.mkdir(parents=True, exist_ok=True)

    def open(
        self,
        freq_hz: float,
        sample_rate: int,
        hw_type: str = "",
        notes: str = "",
    ) -> SigMFRecording:
        ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base = self._iq_path / f"iq_{freq_hz / 1e6:.3f}MHz_{ts}"
        return SigMFRecording(base, freq_hz, sample_rate, hw_type, notes)


class SigMFRecording:

    def __init__(
        self,
        base_path: Path,
        freq_hz: float,
        sample_rate: int,
        hw_type: str,
        notes: str,
    ) -> None:
        self._data_path:   Path = Path(f"{base_path}.sigmf-data")
        self._meta_path:   Path = Path(f"{base_path}.sigmf-meta")
        self._freq_hz:     float = freq_hz
        self._sample_rate: int   = sample_rate
        self._hw_type:     str   = hw_type
        self._notes:       str   = notes
        self._samples:     int   = 0
        self._started_iso: str   = _utc_now_iso()
        self._annotations: list[dict[str, Any]] = []
        self._file:        BufferedWriter | None = None

    def __enter__(self) -> SigMFRecording:
        self._file = open(self._data_path, "wb")
        log.info("SigMF recording started -> %s", self._data_path.name)
        return self

    def write(self, samples: np.ndarray) -> None:
        if self._file is None:
            raise RuntimeError("SigMFRecording is not open")
        self._file.write(samples.astype(np.complex64).tobytes())
        self._samples += len(samples)

    def annotate(
        self,
        sample_start: int,
        sample_count: int,
        label: str,
        comment: str = "",
    ) -> None:
        self._annotations.append({
            "core:sample_start": sample_start,
            "core:sample_count": sample_count,
            "core:label":        label,
            "core:comment":      comment,
        })

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val:  BaseException | None,
        exc_tb:   object,
    ) -> None:
        if self._file is not None:
            try:
                self._file.flush()
            finally:
                self._file.close()
                self._file = None
        self._write_meta()
        size_mb = (
            self._data_path.stat().st_size / 1e6
            if self._data_path.exists()
            else 0.0
        )
        log.info(
            "SigMF recording closed — %d samples  %.1f MB -> %s",
            self._samples, size_mb, self._data_path.name,
        )

    def _write_meta(self) -> None:
        duration_s = (
            self._samples / self._sample_rate if self._sample_rate else 0.0
        )
        meta: dict[str, Any] = {
            "global": {
                "core:datatype":        _SIGMF_DATATYPE,
                "core:sample_rate":     self._sample_rate,
                "core:version":         _SIGMF_VERSION,
                "core:hw":              self._hw_type,
                "core:description":     self._notes or "APEX SENTINEL capture",
                "core:author":          "rfscanner",
                "core:date":            self._started_iso,
                "rfscanner:duration_s": round(duration_s, 3),
                "rfscanner:samples":    self._samples,
            },
            "captures": [{
                "core:sample_start": 0,
                "core:frequency":    self._freq_hz,
                "core:datetime":     self._started_iso,
            }],
            "annotations": self._annotations,
        }
        with open(self._meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)

    @property
    def data_path(self) -> Path:
        return self._data_path

    @property
    def meta_path(self) -> Path:
        return self._meta_path

    @property
    def samples_written(self) -> int:
        return self._samples
