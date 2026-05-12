from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Iterator

import numpy as np

from modules.rf.rf_config import StorageConfig

log = logging.getLogger(__name__)


SCHEMA_SQL = (
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


class SignalDB:

    def __init__(self, cfg: StorageConfig):
        self.cfg      = cfg
        self.db_path  = cfg.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock       = threading.Lock()
        self._local      = threading.local()
        self._session_id: Optional[int] = None
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()
        log.debug("SignalDB iniciada en %s", self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=True,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA cache_size=-8000")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Sesiones ─────────────────────────────────────────────────────

    def open_session(self, hw_type: str = "", sample_rate: int = 0,
                     notes: str = "") -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at, hw_type, sample_rate, notes) "
                "VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(),
                 hw_type, sample_rate, notes)
            )
            self._session_id = cur.lastrowid
        log.info("Sesion RF abierta — ID=%d", self._session_id)
        return self._session_id

    def close_session(self):
        if not self._session_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), self._session_id)
            )
        log.info("Sesion RF cerrada — ID=%d", self._session_id)
        self._session_id = None

    # ── Señales ──────────────────────────────────────────────────────

    def insert_signal(self, sig) -> int:
        d         = sig.to_dict() if hasattr(sig, "to_dict") else dict(sig)
        banda     = ""
        banda_tipo = ""
        tactica   = 0

        if hasattr(sig, "banda") and sig.banda:
            banda     = sig.banda.get("nombre", "")
            banda_tipo = sig.banda.get("tipo", "")
            tactica   = 1 if sig.banda.get("peligro", False) else 0

        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO signals "
                "(session_id, timestamp, freq_mhz, potencia, snr_db, "
                "bw_khz, piso_dbm, kurtosis, mod_hint, banda, banda_tipo, tactica) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._session_id,
                    d.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    d["freq_mhz"], d["potencia"], d["snr_db"],
                    d["bw_khz"],   d["piso_dbm"],
                    d.get("kurtosis", 0.0),
                    d.get("mod_hint", ""),
                    banda, banda_tipo, tactica,
                )
            )
            return cur.lastrowid

    def insert_signals_batch(self, signals: list) -> int:
        if not signals:
            return 0
        rows = []
        for sig in signals:
            d         = sig.to_dict() if hasattr(sig, "to_dict") else dict(sig)
            banda     = ""
            banda_tipo = ""
            tactica   = 0
            if hasattr(sig, "banda") and sig.banda:
                banda     = sig.banda.get("nombre", "")
                banda_tipo = sig.banda.get("tipo", "")
                tactica   = 1 if sig.banda.get("peligro", False) else 0
            rows.append((
                self._session_id,
                d.get("timestamp", datetime.now(timezone.utc).isoformat()),
                d["freq_mhz"], d["potencia"], d["snr_db"],
                d["bw_khz"],   d["piso_dbm"],
                d.get("kurtosis", 0.0),
                d.get("mod_hint", ""),
                banda, banda_tipo, tactica,
            ))

        with self._lock, self._connect() as conn:
            conn.executemany(
                "INSERT INTO signals "
                "(session_id, timestamp, freq_mhz, potencia, snr_db, "
                "bw_khz, piso_dbm, kurtosis, mod_hint, banda, banda_tipo, tactica) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows
            )
        return len(rows)

    def get_signals(self, session_id: Optional[int] = None,
                    freq_min: float = 0, freq_max: float = 99999,
                    snr_min: float = 0, limit: int = 1000) -> list[dict]:
        sid = session_id or self._session_id
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM signals "
                "WHERE (session_id=? OR ?=0) "
                "AND freq_mhz BETWEEN ? AND ? "
                "AND snr_db >= ? "
                "ORDER BY snr_db DESC LIMIT ?",
                (sid, sid if sid else 0, freq_min, freq_max, snr_min, limit)
            )
            return [dict(row) for row in cur.fetchall()]

    def insert_sweep(self, freq_ini: float, freq_fin: float,
                     paso: float, puntos: int, activas: int):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sweeps "
                "(session_id, timestamp, freq_ini, freq_fin, paso_mhz, puntos, activas) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self._session_id, datetime.now(timezone.utc).isoformat(),
                 freq_ini, freq_fin, paso, puntos, activas)
            )

    def register_iq(self, freq_mhz: float, duration_s: float,
                    sample_rate: int, hw_type: str, filename: str,
                    size_mb: float, notes: str = ""):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO iq_recordings "
                "(session_id, timestamp, freq_mhz, duration_s, sample_rate, "
                "hw_type, filename, size_mb, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self._session_id, datetime.now(timezone.utc).isoformat(),
                 freq_mhz, duration_s, sample_rate,
                 hw_type, filename, size_mb, notes)
            )

    # ── Mantenimiento ────────────────────────────────────────────────

    def purge_old(self, retention_days: int):
        if retention_days <= 0:
            return
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=retention_days)).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE started_at < ?", (cutoff,)
            )
        log.info("Registros anteriores a %s eliminados", cutoff)

    def stats(self) -> dict:
        with self._connect() as conn:
            def count(table: str, where: str = "") -> int:
                q = f"SELECT COUNT(*) FROM {table}"
                if where:
                    q += f" WHERE {where}"
                return conn.execute(q).fetchone()[0]

            return {
                "sessions":   count("sessions"),
                "signals":    count("signals"),
                "sweeps":     count("sweeps"),
                "iq_files":   count("iq_recordings"),
                "db_size_mb": round(
                    self.db_path.stat().st_size / 1e6, 2
                ) if self.db_path.exists() else 0,
            }


# ════════════════════════════════════════════════════════════════════
# CSV EXPORT
# ════════════════════════════════════════════════════════════════════

class CSVExporter:

    SIGNAL_FIELDS = [
        "timestamp", "freq_mhz", "potencia", "snr_db",
        "bw_khz", "piso_dbm", "kurtosis", "mod_hint", "banda",
    ]
    SWEEP_FIELDS = ["freq_mhz", "pot_max", "piso", "snr", "banda"]

    def __init__(self, cfg: StorageConfig):
        self.path = cfg.csv_path

    def export_signals(self, signals: list, freq_mhz: float,
                       hw_type: str = "") -> Path:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        hw_str  = hw_type.replace(" ", "_") if hw_type else "unknown"
        filename = self.path / f"scan_{freq_mhz:.3f}MHz_{hw_str}_{ts}.csv"
        rows    = []
        for sig in signals:
            d = sig.to_dict() if hasattr(sig, "to_dict") else dict(sig)
            rows.append({
                "timestamp": d.get("timestamp", ""),
                "freq_mhz":  d.get("freq_mhz",  ""),
                "potencia":  d.get("potencia",  ""),
                "snr_db":    d.get("snr_db",    ""),
                "bw_khz":    d.get("bw_khz",    ""),
                "piso_dbm":  d.get("piso_dbm",  ""),
                "kurtosis":  d.get("kurtosis",  ""),
                "mod_hint":  d.get("mod_hint",  ""),
                "banda":     d.get("banda",     "—"),
            })
        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=self.SIGNAL_FIELDS)
                w.writeheader()
                w.writerows(rows)
            log.info("CSV señales → %s", filename)
            return filename
        except OSError as e:
            log.error("Error exportando CSV: %s", e)
            raise

    def export_sweep(self, results: list, freq_ini: float,
                     freq_fin: float) -> Path:
        ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = self.path / f"sweep_{freq_ini:.0f}-{freq_fin:.0f}MHz_{ts}.csv"
        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=self.SWEEP_FIELDS)
                w.writeheader()
                for r in results:
                    w.writerow({
                        "freq_mhz": r.get("freq_mhz", ""),
                        "pot_max":  r.get("pot_max",  ""),
                        "piso":     r.get("piso",     ""),
                        "snr":      r.get("snr",      ""),
                        "banda": (
                            r["banda"]["nombre"] if r.get("banda") else "—"
                        ),
                    })
            log.info("CSV barrido → %s", filename)
            return filename
        except OSError as e:
            log.error("Error exportando CSV barrido: %s", e)
            raise


# ════════════════════════════════════════════════════════════════════
# SigMF WRITER — GRABACION STREAMING
# ════════════════════════════════════════════════════════════════════

class SigMFWriter:

    SIGMF_VERSION  = "1.0.0"
    SIGMF_DATATYPE = "cf32_le"

    def __init__(self, cfg: StorageConfig):
        self.iq_path = cfg.iq_path

    def open(self, freq_hz: float, sample_rate: int,
             hw_type: str = "", notes: str = "") -> "SigMFRecording":
        ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base = self.iq_path / f"iq_{freq_hz/1e6:.3f}MHz_{ts}"
        return SigMFRecording(base, freq_hz, sample_rate, hw_type, notes)


class SigMFRecording:

    def __init__(self, base_path: Path, freq_hz: float,
                 sample_rate: int, hw_type: str, notes: str):
        self._base        = base_path
        self._data_path   = Path(str(base_path) + ".sigmf-data")
        self._meta_path   = Path(str(base_path) + ".sigmf-meta")
        self._freq_hz     = freq_hz
        self._sample_rate = sample_rate
        self._hw_type     = hw_type
        self._notes       = notes
        self._samples     = 0
        self._started     = datetime.now(timezone.utc).isoformat()
        self._file        = None
        self._annotations: list[dict] = []

    def __enter__(self) -> "SigMFRecording":
        self._file = open(self._data_path, "wb")
        log.info("Grabacion SigMF iniciada → %s", self._data_path.name)
        return self

    def write(self, samples: np.ndarray):
        if self._file is None:
            raise RuntimeError("SigMFRecording no esta abierta")
        data = samples.astype(np.complex64)
        self._file.write(data.tobytes())
        self._samples += len(samples)

    def annotate(self, sample_start: int, sample_count: int,
                 label: str, comment: str = ""):
        self._annotations.append({
            "core:sample_start": sample_start,
            "core:sample_count": sample_count,
            "core:label":        label,
            "core:comment":      comment,
        })

    def __exit__(self, *_):
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None
        self._write_meta()
        size_mb = self._data_path.stat().st_size / 1e6
        log.info(
            "Grabacion SigMF finalizada — %d muestras  %.1f MB → %s",
            self._samples, size_mb, self._data_path.name,
        )

    def _write_meta(self):
        duration_s = self._samples / self._sample_rate if self._sample_rate else 0
        meta = {
            "global": {
                "core:datatype":    SigMFWriter.SIGMF_DATATYPE,
                "core:sample_rate": self._sample_rate,
                "core:version":     SigMFWriter.SIGMF_VERSION,
                "core:hw":          self._hw_type,
                "core:description": self._notes or "APEX SENTINEL capture",
                "core:author":      "rfscanner",
                "core:date":        self._started,
                "rfscanner:duration_s": round(duration_s, 3),
                "rfscanner:samples":    self._samples,
            },
            "captures": [{
                "core:sample_start": 0,
                "core:frequency":    self._freq_hz,
                "core:datetime":     self._started,
            }],
            "annotations": self._annotations,
        }
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @property
    def data_path(self) -> Path:
        return self._data_path

    @property
    def meta_path(self) -> Path:
        return self._meta_path

    @property
    def samples_written(self) -> int:
        return self._samples
