from __future__ import annotations
from typing import Any

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


log = logging.getLogger(__name__)

SCHEMA_VERSION = 3


class RFDatabase:

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._schema_init()
        log.debug("RFDatabase abierta: %s", self.db_path)

    # ── Conexión por hilo (thread-local) ─────────────────────────────

    def _conn(self) -> sqlite3.Connection:
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
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=134217728")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _tx(self) -> None:
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ── Esquema ───────────────────────────────────────────────────────

    def _schema_init(self) -> None:
        ddl = [
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
            "CREATE INDEX IF NOT EXISTS idx_senales_freq      ON senales(freq_mhz)",
            "CREATE INDEX IF NOT EXISTS idx_senales_ts        ON senales(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_senales_snr       ON senales(snr_db DESC)",
            "CREATE INDEX IF NOT EXISTS idx_senales_banda     ON senales(banda)",
            "CREATE INDEX IF NOT EXISTS idx_senales_escaneo   ON senales(escaneo_id)",
        ]
        with self._tx() as db:
            for stmt in ddl:
                db.execute(stmt)
            db.execute(
                "INSERT OR IGNORE INTO schema_version(id, version, created) "
                "VALUES (1, ?, ?)",
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat())
            )

    # ── Inserción ────────────────────────────────────────────────────

    def iniciar_escaneo(self, freq_mhz: float, hardware: str,
                        sample_rate: int, fft_size: int,
                        notas: str = "") -> int:
        with self._tx() as db:
            cur = db.execute(
                "INSERT INTO escaneos "
                "(timestamp, freq_mhz, hardware, sample_rate, fft_size, notas) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(),
                 freq_mhz, hardware, sample_rate, fft_size, notas)
            )
            return cur.lastrowid

    def finalizar_escaneo(self, escaneo_id: int, duracion_s: float) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE escaneos SET duracion_s=?, "
                "n_senales=(SELECT COUNT(*) FROM senales WHERE escaneo_id=?) "
                "WHERE id=?",
                (duracion_s, escaneo_id, escaneo_id)
            )

    def insertar_senal(self, pico: dict[str, Any], escaneo_id: int | None = None) -> None:
        banda = pico.get("banda")
        with self._tx() as db:
            db.execute(
                "INSERT INTO senales "
                "(escaneo_id, timestamp, freq_mhz, potencia, snr_db, "
                "bw_khz, piso_dbm, kurtosis, mod_hint, banda, tipo_banda, hardware) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    escaneo_id,
                    pico.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    pico["freq_mhz"],
                    pico["potencia"],
                    pico["snr_db"],
                    pico.get("bw_khz"),
                    pico.get("piso_dbm"),
                    pico.get("kurtosis", 0.0),
                    pico.get("mod_hint"),
                    banda["nombre"] if banda else None,
                    banda["tipo"]   if banda else None,
                    pico.get("hardware"),
                )
            )

    def insertar_senales_bulk(self, picos: list[dict[str, Any]],
                               escaneo_id: int | None = None) -> None:
        if not picos:
            return
        ts_now = datetime.now(timezone.utc).isoformat()
        rows   = []
        for p in picos:
            banda = p.get("banda")
            rows.append((
                escaneo_id,
                p.get("timestamp", ts_now),
                p["freq_mhz"], p["potencia"], p["snr_db"],
                p.get("bw_khz"), p.get("piso_dbm"),
                p.get("kurtosis", 0.0), p.get("mod_hint"),
                banda["nombre"] if banda else None,
                banda["tipo"]   if banda else None,
                p.get("hardware"),
            ))
        with self._tx() as db:
            db.executemany(
                "INSERT INTO senales "
                "(escaneo_id, timestamp, freq_mhz, potencia, snr_db, "
                "bw_khz, piso_dbm, kurtosis, mod_hint, banda, tipo_banda, hardware) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows
            )

    def insertar_barrido(self, freq_ini: float, freq_fin: float,
                          paso_mhz: float, hardware: str, resultados: list) -> None:
        import json
        datos = [
            {
                "freq": r["freq_mhz"],
                "pot":  r["pot_max"],
                "piso": r["piso"],
                "snr":  r["snr"],
                "banda": r["banda"]["nombre"] if r.get("banda") else None,
            }
            for r in resultados
        ]
        with self._tx() as db:
            db.execute(
                "INSERT INTO barridos "
                "(timestamp, freq_ini, freq_fin, paso_mhz, hardware, "
                "n_puntos, datos_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    freq_ini, freq_fin, paso_mhz, hardware,
                    len(resultados), json.dumps(datos),
                )
            )

    # ── Consultas ────────────────────────────────────────────────────

    def consultar_senales(self,
                          freq_min: float | None = None,
                          freq_max: float | None = None,
                          snr_min:  float | None = None,
                          banda:    str | None   = None,
                          horas:    int | None   = None,
                          limit:    int = 200) -> list[dict[str, Any]]:
        condiciones: list[str] = []
        params:      list      = []

        if freq_min is not None:
            condiciones.append("freq_mhz >= ?")
            params.append(freq_min)
        if freq_max is not None:
            condiciones.append("freq_mhz <= ?")
            params.append(freq_max)
        if snr_min is not None:
            condiciones.append("snr_db >= ?")
            params.append(snr_min)
        if banda:
            condiciones.append("banda LIKE ?")
            params.append(f"%{banda}%")
        if horas is not None:
            desde = (datetime.now(timezone.utc)
                     - timedelta(hours=horas)).isoformat()
            condiciones.append("timestamp >= ?")
            params.append(desde)

        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        params.append(limit)

        rows = self._conn().execute(
            f"SELECT * FROM senales {where} ORDER BY snr_db DESC LIMIT ?",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    def estadisticas(self) -> dict:
        row = self._conn().execute("""
            SELECT
                COUNT(*)                 AS total_senales,
                COUNT(DISTINCT freq_mhz) AS freqs_unicas,
                COUNT(DISTINCT banda)    AS bandas_vistas,
                MAX(snr_db)              AS snr_max,
                ROUND(AVG(snr_db), 2)    AS snr_medio,
                MAX(potencia)            AS pot_max,
                MIN(timestamp)           AS primera,
                MAX(timestamp)           AS ultima
            FROM senales
        """).fetchone()

        escaneos = self._conn().execute(
            "SELECT COUNT(*) FROM escaneos"
        ).fetchone()[0]
        barridos = self._conn().execute(
            "SELECT COUNT(*) FROM barridos"
        ).fetchone()[0]

        return {**dict(row), "escaneos": escaneos, "barridos": barridos}

    def top_senales(self, n: int = 10) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT freq_mhz, potencia, snr_db, bw_khz, kurtosis, "
            "mod_hint, banda, timestamp FROM senales "
            "ORDER BY snr_db DESC LIMIT ?",
            (n,)
        ).fetchall()
        return [dict(r) for r in rows]

    def frecuencias_activas(self, snr_min: float = 10.0,
                            horas: int = 24) -> list[dict[str, Any]]:
        desde = (datetime.now(timezone.utc)
                 - timedelta(hours=horas)).isoformat()
        rows  = self._conn().execute("""
            SELECT
                ROUND(freq_mhz, 2)  AS freq_mhz,
                COUNT(*)            AS detecciones,
                MAX(snr_db)         AS snr_max,
                AVG(potencia)       AS pot_media,
                banda
            FROM senales
            WHERE timestamp >= ? AND snr_db >= ?
            GROUP BY ROUND(freq_mhz, 2)
            HAVING detecciones >= 2
            ORDER BY detecciones DESC
            LIMIT 50
        """, (desde, snr_min)).fetchall()
        return [dict(r) for r in rows]

    # ── Mantenimiento ────────────────────────────────────────────────

    def limpiar_antiguas(self, dias: int) -> None:
        if dias <= 0:
            return
        limite = (datetime.now(timezone.utc)
                  - timedelta(days=dias)).isoformat()
        with self._tx() as db:
            result = db.execute(
                "DELETE FROM senales WHERE timestamp < ?", (limite,)
            )
            db.execute("DELETE FROM escaneos WHERE timestamp < ?", (limite,))
            db.execute("DELETE FROM barridos WHERE timestamp < ?", (limite,))
        log.info("Limpieza: %d señales eliminadas (>%d dias)",
                 result.rowcount, dias)
        self._conn().execute("VACUUM")

    def exportar_csv(self, ruta: Path,
                     freq_min: float | None = None,
                     freq_max: float | None = None) -> None:
        import csv
        senales = self.consultar_senales(
            freq_min=freq_min, freq_max=freq_max, limit=100_000
        )
        if not senales:
            log.warning("Sin señales para exportar")
            return
        campos = [
            "timestamp", "freq_mhz", "potencia", "snr_db",
            "bw_khz", "piso_dbm", "kurtosis", "mod_hint",
            "banda", "tipo_banda", "hardware"
        ]
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            w.writeheader()
            w.writerows(senales)
        log.info("Exportadas %d señales a %s", len(senales), ruta)

    # ── Cierre ───────────────────────────────────────────────────────

    def cerrar(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            self._local.conn = None
            log.debug("RFDatabase cerrada")

    def __enter__(self) -> None:
        return self

    def __exit__(self, *_) -> None:
        self.cerrar()
