from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Generator, Iterator

log: Final = logging.getLogger("sentinel.rf.database")

SCHEMA_VERSION: Final[int] = 4

_WAL_PRAGMAS: Final[tuple[str, ...]] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA cache_size=-16000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",
    "PRAGMA page_size=4096",
    "PRAGMA wal_autocheckpoint=1000",
)

_DDL_STATEMENTS: Final[tuple[str, ...]] = (
    """CREATE TABLE IF NOT EXISTS schema_version (
        id      INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL,
        created TEXT    NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS escaneos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        freq_mhz    REAL    NOT NULL,
        duracion_s  REAL,
        hardware    TEXT,
        sample_rate INTEGER,
        fft_size    INTEGER,
        n_senales   INTEGER DEFAULT 0,
        notas       TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS senales (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        escaneo_id  INTEGER REFERENCES escaneos(id) ON DELETE CASCADE,
        timestamp   TEXT    NOT NULL,
        freq_mhz    REAL    NOT NULL,
        potencia    REAL    NOT NULL,
        snr_db      REAL    NOT NULL,
        bw_khz      REAL,
        piso_dbm    REAL,
        kurtosis    REAL    DEFAULT 0.0,
        mod_hint    TEXT,
        banda       TEXT,
        tipo_banda  TEXT,
        hardware    TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS barridos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        freq_ini    REAL    NOT NULL,
        freq_fin    REAL    NOT NULL,
        paso_mhz    REAL,
        hardware    TEXT,
        n_puntos    INTEGER,
        datos_json  TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_senales_freq    ON senales(freq_mhz)",
    "CREATE INDEX IF NOT EXISTS idx_senales_ts      ON senales(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_senales_snr     ON senales(snr_db DESC)",
    "CREATE INDEX IF NOT EXISTS idx_senales_banda   ON senales(banda)",
    "CREATE INDEX IF NOT EXISTS idx_senales_escaneo ON senales(escaneo_id)",
    "CREATE INDEX IF NOT EXISTS idx_senales_freq_ts ON senales(freq_mhz, timestamp)",
)

_INSERT_SENAL_SQL: Final[str] = (
    "INSERT INTO senales "
    "(escaneo_id, timestamp, freq_mhz, potencia, snr_db, "
    "bw_khz, piso_dbm, kurtosis, mod_hint, banda, tipo_banda, hardware) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_INSERT_ESCANEO_SQL: Final[str] = (
    "INSERT INTO escaneos "
    "(timestamp, freq_mhz, hardware, sample_rate, fft_size, notas) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)

_INSERT_BARRIDO_SQL: Final[str] = (
    "INSERT INTO barridos "
    "(timestamp, freq_ini, freq_fin, paso_mhz, hardware, n_puntos, datos_json) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)

_STATS_SQL: Final[str] = """
    SELECT
        COUNT(*)                 AS total_senales,
        COUNT(DISTINCT freq_mhz) AS freqs_unicas,
        COUNT(DISTINCT banda)    AS bandas_vistas,
        MAX(snr_db)              AS snr_max,
        ROUND(AVG(snr_db), 2)   AS snr_medio,
        MAX(potencia)            AS pot_max,
        MIN(timestamp)           AS primera,
        MAX(timestamp)           AS ultima
    FROM senales
"""

_ACTIVE_FREQS_SQL: Final[str] = """
    SELECT
        ROUND(freq_mhz, 2) AS freq_mhz,
        COUNT(*)           AS detecciones,
        MAX(snr_db)        AS snr_max,
        AVG(potencia)      AS pot_media,
        banda
    FROM senales
    WHERE timestamp >= ? AND snr_db >= ?
    GROUP BY ROUND(freq_mhz, 2)
    HAVING detecciones >= 2
    ORDER BY detecciones DESC
    LIMIT 50
"""

_CSV_EXPORT_FIELDS: Final[tuple[str, ...]] = (
    "timestamp", "freq_mhz", "potencia", "snr_db",
    "bw_khz", "piso_dbm", "kurtosis", "mod_hint",
    "banda", "tipo_banda", "hardware",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_ago_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _extract_banda_tuple(signal_dict: dict[str, Any]) -> tuple[str | None, str | None]:
    banda = signal_dict.get("banda")
    if not banda or not isinstance(banda, dict):
        return None, None
    return banda.get("nombre"), banda.get("tipo")


def _build_senal_row(
    signal_dict: dict[str, Any],
    escaneo_id: int | None,
    fallback_ts: str,
) -> tuple[Any, ...]:
    banda_nombre, banda_tipo = _extract_banda_tuple(signal_dict)
    return (
        escaneo_id,
        signal_dict.get("timestamp", fallback_ts),
        signal_dict["freq_mhz"],
        signal_dict["potencia"],
        signal_dict["snr_db"],
        signal_dict.get("bw_khz"),
        signal_dict.get("piso_dbm"),
        signal_dict.get("kurtosis", 0.0),
        signal_dict.get("mod_hint"),
        banda_nombre,
        banda_tipo,
        signal_dict.get("hardware"),
    )


def _build_barrido_payload(resultados: list[dict[str, Any]]) -> str:
    payload = [
        {
            "freq": r["freq_mhz"],
            "pot": r["pot_max"],
            "piso": r["piso"],
            "snr": r["snr"],
            "banda": r["banda"]["nombre"] if r.get("banda") else None,
        }
        for r in resultados
    ]
    return json.dumps(payload, separators=(",", ":"))


def _build_where_clause(
    freq_min: float | None,
    freq_max: float | None,
    snr_min: float | None,
    banda: str | None,
    horas: int | None,
) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if freq_min is not None:
        conditions.append("freq_mhz >= ?")
        params.append(freq_min)
    if freq_max is not None:
        conditions.append("freq_mhz <= ?")
        params.append(freq_max)
    if snr_min is not None:
        conditions.append("snr_db >= ?")
        params.append(snr_min)
    if banda:
        conditions.append("banda LIKE ?")
        params.append(f"%{banda}%")
    if horas is not None:
        conditions.append("timestamp >= ?")
        params.append(_hours_ago_iso(horas))

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, params


class _ThreadLocalConnectionPool:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._local = threading.local()

    def acquire(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=True,
            isolation_level=None,
            cached_statements=128,
        )
        conn.row_factory = sqlite3.Row
        for pragma in _WAL_PRAGMAS:
            conn.execute(pragma)
        self._local.conn = conn
        log.debug("New thread-local connection created for thread %s", threading.current_thread().name)
        return conn

    def release_current_thread(self) -> None:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            return
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception as exc:
            log.warning("Error closing connection: %s", exc)
        finally:
            self._local.conn = None

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self.acquire()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except Exception as rollback_exc:
                log.error("ROLLBACK failed: %s", rollback_exc)
            raise


class RFDatabase:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = _ThreadLocalConnectionPool(self._db_path)
        self._schema_init()
        log.debug("RFDatabase opened: %s", self._db_path)

    def _schema_init(self) -> None:
        with self._pool.transaction() as db:
            for stmt in _DDL_STATEMENTS:
                db.execute(stmt)
            db.execute(
                "INSERT OR IGNORE INTO schema_version(id, version, created) VALUES (1, ?, ?)",
                (SCHEMA_VERSION, _utc_now_iso()),
            )
        self._migrate_schema_if_needed()

    def _migrate_schema_if_needed(self) -> None:
        row = self._pool.acquire().execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()
        if row is None:
            return
        stored_version: int = row[0]
        if stored_version >= SCHEMA_VERSION:
            return
        log.info(
            "Schema migration: v%d -> v%d on %s",
            stored_version, SCHEMA_VERSION, self._db_path,
        )
        with self._pool.transaction() as db:
            if stored_version < 4:
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_senales_freq_ts "
                    "ON senales(freq_mhz, timestamp)"
                )
            db.execute(
                "UPDATE schema_version SET version = ? WHERE id = 1",
                (SCHEMA_VERSION,),
            )

    def iniciar_escaneo(
        self,
        freq_mhz: float,
        hardware: str,
        sample_rate: int,
        fft_size: int,
        notas: str = "",
    ) -> int:
        with self._pool.transaction() as db:
            cursor = db.execute(
                _INSERT_ESCANEO_SQL,
                (_utc_now_iso(), freq_mhz, hardware, sample_rate, fft_size, notas),
            )
            return cursor.lastrowid

    def finalizar_escaneo(self, escaneo_id: int, duracion_s: float) -> None:
        with self._pool.transaction() as db:
            db.execute(
                "UPDATE escaneos SET duracion_s = ?, "
                "n_senales = (SELECT COUNT(*) FROM senales WHERE escaneo_id = ?) "
                "WHERE id = ?",
                (duracion_s, escaneo_id, escaneo_id),
            )

    def insertar_senal(
        self,
        signal_dict: dict[str, Any],
        escaneo_id: int | None = None,
    ) -> None:
        row = _build_senal_row(signal_dict, escaneo_id, _utc_now_iso())
        with self._pool.transaction() as db:
            db.execute(_INSERT_SENAL_SQL, row)

    def insertar_senales_bulk(
        self,
        signals: list[dict[str, Any]],
        escaneo_id: int | None = None,
    ) -> None:
        if not signals:
            return
        fallback_ts = _utc_now_iso()
        rows = [_build_senal_row(s, escaneo_id, fallback_ts) for s in signals]
        with self._pool.transaction() as db:
            db.executemany(_INSERT_SENAL_SQL, rows)

    def insertar_barrido(
        self,
        freq_ini: float,
        freq_fin: float,
        paso_mhz: float,
        hardware: str,
        resultados: list[dict[str, Any]],
    ) -> None:
        payload_json = _build_barrido_payload(resultados)
        with self._pool.transaction() as db:
            db.execute(
                _INSERT_BARRIDO_SQL,
                (
                    _utc_now_iso(),
                    freq_ini,
                    freq_fin,
                    paso_mhz,
                    hardware,
                    len(resultados),
                    payload_json,
                ),
            )

    def consultar_senales(
        self,
        freq_min: float | None = None,
        freq_max: float | None = None,
        snr_min: float | None = None,
        banda: str | None = None,
        horas: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        where_clause, params = _build_where_clause(freq_min, freq_max, snr_min, banda, horas)
        params.append(limit)
        rows = self._pool.acquire().execute(
            f"SELECT * FROM senales {where_clause} ORDER BY snr_db DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def iter_senales(
        self,
        freq_min: float | None = None,
        freq_max: float | None = None,
        snr_min: float | None = None,
        banda: str | None = None,
        horas: int | None = None,
        chunk_size: int = 500,
    ) -> Iterator[dict[str, Any]]:
        where_clause, params = _build_where_clause(freq_min, freq_max, snr_min, banda, horas)
        cursor = self._pool.acquire().execute(
            f"SELECT * FROM senales {where_clause} ORDER BY snr_db DESC",
            params,
        )
        while True:
            chunk = cursor.fetchmany(chunk_size)
            if not chunk:
                break
            yield from (dict(r) for r in chunk)

    def estadisticas(self) -> dict[str, Any]:
        conn = self._pool.acquire()
        signal_stats = dict(conn.execute(_STATS_SQL).fetchone() or {})
        signal_stats["escaneos"] = conn.execute("SELECT COUNT(*) FROM escaneos").fetchone()[0]
        signal_stats["barridos"] = conn.execute("SELECT COUNT(*) FROM barridos").fetchone()[0]
        return signal_stats

    def top_senales(self, n: int = 10) -> list[dict[str, Any]]:
        rows = self._pool.acquire().execute(
            "SELECT freq_mhz, potencia, snr_db, bw_khz, kurtosis, "
            "mod_hint, banda, timestamp FROM senales "
            "ORDER BY snr_db DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(r) for r in rows]

    def frecuencias_activas(
        self,
        snr_min: float = 10.0,
        horas: int = 24,
    ) -> list[dict[str, Any]]:
        rows = self._pool.acquire().execute(
            _ACTIVE_FREQS_SQL,
            (_hours_ago_iso(horas), snr_min),
        ).fetchall()
        return [dict(r) for r in rows]

    def limpiar_antiguas(self, dias: int) -> None:
        if dias <= 0:
            return
        cutoff_ts = _days_ago_iso(dias)
        with self._pool.transaction() as db:
            deleted_signals = db.execute(
                "DELETE FROM senales WHERE timestamp < ?", (cutoff_ts,)
            ).rowcount
            db.execute("DELETE FROM escaneos WHERE timestamp < ?", (cutoff_ts,))
            db.execute("DELETE FROM barridos WHERE timestamp < ?", (cutoff_ts,))
        log.info("Purge: %d signals removed (retention > %d days)", deleted_signals, dias)
        self._pool.acquire().execute("VACUUM")

    def exportar_csv(
        self,
        ruta: Path,
        freq_min: float | None = None,
        freq_max: float | None = None,
        snr_min: float | None = None,
        horas: int | None = None,
    ) -> int:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        exported = 0
        with ruta.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_EXPORT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in self.iter_senales(
                freq_min=freq_min,
                freq_max=freq_max,
                snr_min=snr_min,
                horas=horas,
            ):
                writer.writerow(row)
                exported += 1
        if exported == 0:
            ruta.unlink(missing_ok=True)
            log.warning("No signals matched export criteria — file not written")
        else:
            log.info("Exported %d signals to %s", exported, ruta)
        return exported

    def cerrar(self) -> None:
        self._pool.release_current_thread()
        log.debug("RFDatabase closed: %s", self._db_path)

    def __enter__(self) -> RFDatabase:
        return self

    def __exit__(self, *_: Any) -> None:
        self.cerrar()
