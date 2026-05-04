import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Versión del esquema — incrementar si cambia la estructura
SCHEMA_VERSION = 2


class RFDatabase:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._conectar()
        self._crear_esquema()
        log.debug(f"Base de datos RF abierta: {self.db_path}")

    # ── Conexión ──────────────────────────────────────────────────────

    def _conectar(self):
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,   # múltiples hilos leen
            isolation_level=None,      # autocommit — control manual
        )
        self._conn.row_factory = sqlite3.Row
        # WAL mode: lecturas y escrituras concurrentes sin bloqueo completo
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA cache_size=4000")

    @contextmanager
    def _tx(self):
        """Context manager para transacciones explícitas."""
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ── Esquema ───────────────────────────────────────────────────────

    def _crear_esquema(self):
        """
        Crea las tablas al esquema actual.
        NOTA: executescript() hace COMMIT implícito con isolation_level=None,
        por eso usamos execute() individual dentro de _tx().
        """
        ddl = [
            """CREATE TABLE IF NOT EXISTS version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL, created TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS escaneos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, freq_mhz REAL NOT NULL,
                duracion_s REAL, hardware TEXT, sample_rate INTEGER,
                fft_size INTEGER, n_senales INTEGER DEFAULT 0, notas TEXT)""",
            """CREATE TABLE IF NOT EXISTS senales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                escaneo_id INTEGER REFERENCES escaneos(id) ON DELETE CASCADE,
                timestamp TEXT NOT NULL, freq_mhz REAL NOT NULL,
                potencia REAL NOT NULL, snr_db REAL NOT NULL,
                bw_khz REAL, piso_dbm REAL, banda TEXT,
                tipo_banda TEXT, hardware TEXT)""",
            """CREATE TABLE IF NOT EXISTS barridos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, freq_ini REAL NOT NULL,
                freq_fin REAL NOT NULL, paso_mhz REAL,
                hardware TEXT, n_puntos INTEGER, datos_json TEXT)""",
            "CREATE INDEX IF NOT EXISTS idx_senales_freq      ON senales(freq_mhz)",
            "CREATE INDEX IF NOT EXISTS idx_senales_timestamp ON senales(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_senales_snr       ON senales(snr_db DESC)",
            "CREATE INDEX IF NOT EXISTS idx_senales_banda     ON senales(banda)",
        ]
        with self._tx() as db:
            for stmt in ddl:
                db.execute(stmt)
            db.execute(
                "INSERT OR IGNORE INTO version(id, version, created) VALUES (1, ?, ?)",
                (SCHEMA_VERSION, datetime.now().isoformat())
            )

    # ── Inserción ────────────────────────────────────────────────────

    def iniciar_escaneo(self, freq_mhz: float, hardware: str,
                        sample_rate: int, fft_size: int,
                        notas: str = "") -> int:
        """
        Registra el inicio de un escaneo.
        Retorna el escaneo_id para asociar señales detectadas.
        """
        with self._tx() as db:
            cur = db.execute("""
                INSERT INTO escaneos
                    (timestamp, freq_mhz, hardware, sample_rate, fft_size, notas)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), freq_mhz, hardware,
                  sample_rate, fft_size, notas))
            return cur.lastrowid

    def finalizar_escaneo(self, escaneo_id: int, duracion_s: float):
        """Actualiza duración y conteo de señales al terminar."""
        with self._tx() as db:
            db.execute("""
                UPDATE escaneos SET
                    duracion_s = ?,
                    n_senales  = (
                        SELECT COUNT(*) FROM senales
                        WHERE escaneo_id = ?
                    )
                WHERE id = ?
            """, (duracion_s, escaneo_id, escaneo_id))

    def insertar_senal(self, pico: dict, escaneo_id: Optional[int] = None):
        """
        Inserta una señal detectada en la base de datos.

        Args:
            pico: dict con freq_mhz, potencia, snr_db, bw_khz, etc.
            escaneo_id: ID del escaneo al que pertenece (puede ser None)
        """
        banda = pico.get("banda")
        with self._tx() as db:
            db.execute("""
                INSERT INTO senales
                    (escaneo_id, timestamp, freq_mhz, potencia,
                     snr_db, bw_khz, piso_dbm, banda, tipo_banda, hardware)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                escaneo_id,
                pico.get("timestamp", datetime.now().isoformat()),
                pico["freq_mhz"],
                pico["potencia"],
                pico["snr_db"],
                pico.get("bw_khz"),
                pico.get("piso_dbm"),
                banda["nombre"] if banda else None,
                banda["tipo"] if banda else None,
                pico.get("hardware"),
            ))

    def insertar_senales_bulk(self, picos: list,
                              escaneo_id: Optional[int] = None):
        """Inserta múltiples señales en una sola transacción."""
        if not picos:
            return
        ts_now = datetime.now().isoformat()
        rows = []
        for p in picos:
            banda = p.get("banda")
            rows.append((
                escaneo_id,
                p.get("timestamp", ts_now),
                p["freq_mhz"],
                p["potencia"],
                p["snr_db"],
                p.get("bw_khz"),
                p.get("piso_dbm"),
                banda["nombre"] if banda else None,
                banda["tipo"] if banda else None,
                p.get("hardware"),
            ))
        with self._tx() as db:
            db.executemany("""
                INSERT INTO senales
                    (escaneo_id, timestamp, freq_mhz, potencia,
                     snr_db, bw_khz, piso_dbm, banda, tipo_banda, hardware)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

    def insertar_barrido(self, freq_ini: float, freq_fin: float,
                         paso_mhz: float, hardware: str,
                         resultados: list):
        """Guarda los resultados completos de un barrido."""
        import json
        # Serializar solo los campos básicos (sin objetos banda complejos)
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
            db.execute("""
                INSERT INTO barridos
                    (timestamp, freq_ini, freq_fin, paso_mhz,
                     hardware, n_puntos, datos_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                freq_ini, freq_fin, paso_mhz,
                hardware, len(resultados),
                json.dumps(datos),
            ))

    # ── Consultas ────────────────────────────────────────────────────

    def consultar_senales(self,
                          freq_min: Optional[float] = None,
                          freq_max: Optional[float] = None,
                          snr_min:  Optional[float] = None,
                          banda:    Optional[str] = None,
                          horas:    Optional[int] = None,
                          limit:    int = 200) -> list[dict]:
        """
        Consulta señales con filtros opcionales.

        Args:
            freq_min/freq_max: rango de frecuencias en MHz
            snr_min:           SNR mínimo en dB
            banda:             nombre de banda (búsqueda parcial)
            horas:             solo señales de las últimas N horas
            limit:             máximo de resultados

        Returns:
            Lista de dicts con los campos de la señal
        """
        condiciones = []
        params: list = []

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
            desde = (datetime.now() - timedelta(hours=horas)).isoformat()
            condiciones.append("timestamp >= ?")
            params.append(desde)

        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        params.append(limit)

        rows = self._conn.execute(f"""
            SELECT * FROM senales
            {where}
            ORDER BY snr_db DESC
            LIMIT ?
        """, params).fetchall()

        return [dict(r) for r in rows]

    def estadisticas(self) -> dict:
        """Resumen estadístico de la base de datos."""
        row = self._conn.execute("""
            SELECT
                COUNT(*)                       as total_senales,
                COUNT(DISTINCT freq_mhz)       as freqs_unicas,
                COUNT(DISTINCT banda)          as bandas_vistas,
                MAX(snr_db)                    as snr_max,
                AVG(snr_db)                    as snr_medio,
                MAX(potencia)                  as pot_max,
                MIN(timestamp)                 as primera,
                MAX(timestamp)                 as ultima
            FROM senales
        """).fetchone()

        escaneos = self._conn.execute(
            "SELECT COUNT(*) FROM escaneos"
        ).fetchone()[0]

        barridos = self._conn.execute(
            "SELECT COUNT(*) FROM barridos"
        ).fetchone()[0]

        return {
            **dict(row),
            "escaneos":  escaneos,
            "barridos":  barridos,
        }

    def top_senales(self, n: int = 10) -> list[dict]:
        """Las N señales más fuertes (por SNR) de toda la historia."""
        rows = self._conn.execute("""
            SELECT freq_mhz, potencia, snr_db, bw_khz, banda, timestamp
            FROM senales
            ORDER BY snr_db DESC
            LIMIT ?
        """, (n,)).fetchall()
        return [dict(r) for r in rows]

    def frecuencias_activas(self, snr_min: float = 10.0,
                            horas: int = 24) -> list[dict]:
        """
        Frecuencias con actividad recurrente en las últimas N horas.
        Agrupa por bins de 10 kHz para detectar señales persistentes.
        """
        desde = (datetime.now() - timedelta(hours=horas)).isoformat()
        rows = self._conn.execute("""
            SELECT
                ROUND(freq_mhz, 2)  as freq_mhz,
                COUNT(*)            as detecciones,
                MAX(snr_db)         as snr_max,
                AVG(potencia)       as pot_media,
                banda
            FROM senales
            WHERE timestamp >= ?
              AND snr_db >= ?
            GROUP BY ROUND(freq_mhz, 2)
            HAVING detecciones >= 2
            ORDER BY detecciones DESC
            LIMIT 50
        """, (desde, snr_min)).fetchall()
        return [dict(r) for r in rows]

    # ── Mantenimiento ────────────────────────────────────────────────

    def limpiar_antiguas(self, dias: int):
        """Elimina registros más antiguos de N días."""
        if dias <= 0:
            return
        limite = (datetime.now() - timedelta(days=dias)).isoformat()
        with self._tx() as db:
            resultado = db.execute(
                "DELETE FROM senales WHERE timestamp < ?", (limite,)
            )
            db.execute(
                "DELETE FROM escaneos WHERE timestamp < ?", (limite,)
            )
            db.execute(
                "DELETE FROM barridos WHERE timestamp < ?", (limite,)
            )
        log.info(
            f"Limpieza DB: {resultado.rowcount} señales eliminadas "
            f"(> {dias} días)"
        )
        self._conn.execute("VACUUM")

    def exportar_csv(self, ruta: Path,
                     freq_min: Optional[float] = None,
                     freq_max: Optional[float] = None):
        """Exporta señales filtradas a CSV."""
        import csv
        senales = self.consultar_senales(
            freq_min=freq_min, freq_max=freq_max, limit=100_000
        )
        if not senales:
            log.warning("No hay señales para exportar")
            return
        campos = ["timestamp", "freq_mhz", "potencia", "snr_db",
                  "bw_khz", "piso_dbm", "banda", "tipo_banda", "hardware"]
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            w.writeheader()
            w.writerows(senales)
        log.info(f"Exportadas {len(senales)} señales a {ruta}")

    # ── Cierre ───────────────────────────────────────────────────────

    def cerrar(self):
        if self._conn:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._conn = None
            log.debug("Base de datos RF cerrada")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()
