"""
╔══════════════════════════════════════════════════════════════════╗
║  APEX SENTINEL — ANUBIS OS  v2.2                                 ║
║  Security.py · Módulo de cifrado Fernet                          ║
╠══════════════════════════════════════════════════════════════════╣
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("sentinel.security")

# Rutas absolutas basadas en la ubicación del módulo
_HERE = Path(__file__).resolve().parent
_KEY_DIR = _HERE / "data" / "security"
_KEY_FILE = _KEY_DIR / "anubis_master.key"
_BACKUP_DIR = _KEY_DIR / "key_backups"


class SecurityModule:
    """
    Módulo de cifrado simétrico para APEX SENTINEL.

    La clave Fernet se almacena en data/security/anubis_master.key
    con permisos 0o600 (solo lectura del propietario en POSIX).

    Uso:
        sec = SecurityModule(sentinel)
        sec.encriptar_archivo("data/evidence/captura.pcap")
        sec.desencriptar_archivo("data/evidence/captura.pcap")
        sec.rotar_clave(archivos_cifrados=["archivo1", "archivo2"])
    """

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self._fernet: Fernet | None = None
        self._inicializar_clave()

    # ── Inicialización ─────────────────────────────────────────────────

    def _inicializar_clave(self) -> None:
        """Carga o genera la clave maestra Fernet."""
        _KEY_DIR.mkdir(parents=True, exist_ok=True)
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        if _KEY_FILE.exists():
            self._fernet = self._cargar_clave(_KEY_FILE)
        else:
            self._fernet = self._generar_clave()

    def _generar_clave(self) -> Fernet:
        """Genera una nueva clave Fernet y la guarda con permisos restrictivos."""
        clave = Fernet.generate_key()
        try:
            _KEY_FILE.write_bytes(clave)
            self._aplicar_permisos(_KEY_FILE)
            log.info(f"Nueva clave maestra generada: {_KEY_FILE}")
        except OSError as e:
            log.error(f"No se pudo guardar la clave maestra: {e}")
            raise RuntimeError(
                f"Error crítico: no se puede guardar la clave de cifrado.") from e
        return Fernet(clave)

    def _cargar_clave(self, ruta: Path) -> Fernet:
        """Carga una clave Fernet desde disco."""
        try:
            clave = ruta.read_bytes()
            return Fernet(clave)
        except (OSError, ValueError) as e:
            log.error(f"No se pudo cargar la clave desde {ruta}: {e}")
            raise RuntimeError(
                f"Clave de cifrado inválida o inaccesible: {ruta}") from e

    @staticmethod
    def _aplicar_permisos(ruta: Path) -> None:
        """Aplica permisos 0o600 en sistemas POSIX."""
        if sys.platform != "win32":
            try:
                ruta.chmod(0o600)
            except OSError as e:
                log.warning(
                    f"No se pudieron establecer permisos en {ruta}: {e}")

    # ── Cifrado / Descifrado ───────────────────────────────────────────

    def encriptar_archivo(self, ruta: str | Path) -> bool:
        """
        Cifra un archivo en su lugar con la clave maestra.

        Retorna True si tuvo éxito, False en caso de error.
        """
        archivo = Path(ruta)
        if not archivo.exists():
            log.warning(f"Archivo no encontrado para cifrar: {archivo}")
            return False
        if not archivo.is_file():
            log.warning(f"La ruta no es un archivo: {archivo}")
            return False

        try:
            datos = archivo.read_bytes()
            cifrado = self._fernet.encrypt(datos)
            archivo.write_bytes(cifrado)
            log.info(f"Archivo cifrado: {archivo}")
            return True
        except OSError as e:
            log.error(f"Error de E/S al cifrar {archivo}: {e}")
            return False
        except Exception as e:
            log.error(f"Error inesperado al cifrar {archivo}: {e}")
            return False

    def desencriptar_archivo(self, ruta: str | Path) -> bool:
        """
        Descifra un archivo en su lugar.

        Retorna True si tuvo éxito, False en caso de error.
        """
        archivo = Path(ruta)
        if not archivo.exists():
            log.warning(f"Archivo no encontrado para descifrar: {archivo}")
            return False

        try:
            datos = archivo.read_bytes()
            original = self._fernet.decrypt(datos)
            archivo.write_bytes(original)
            log.info(f"Archivo descifrado: {archivo}")
            return True
        except InvalidToken:
            log.error(
                f"Token inválido al descifrar {archivo}. "
                "El archivo puede estar corrupto o cifrado con otra clave."
            )
            return False
        except OSError as e:
            log.error(f"Error de E/S al descifrar {archivo}: {e}")
            return False

    def cifrar_datos(self, datos: bytes) -> bytes:
        """Cifra datos en memoria y retorna los bytes cifrados."""
        return self._fernet.encrypt(datos)

    def descifrar_datos(self, datos_cifrados: bytes) -> bytes:
        """
        Descifra datos en memoria.

        Raises:
            InvalidToken — si los datos están corruptos o la clave es incorrecta.
        """
        return self._fernet.decrypt(datos_cifrados)

    # ── Rotación de clave ──────────────────────────────────────────────

    def rotar_clave(self, archivos_cifrados: list[str | Path] | None = None) -> bool:
        """
        Genera una nueva clave Fernet, re-cifra los archivos proporcionados
        con la nueva clave y hace backup de la clave anterior.

        Args:
            archivos_cifrados: Lista de rutas a re-cifrar. Si es None,
                               solo rota la clave sin re-cifrar archivos.

        Retorna True si la rotación fue exitosa.
        """
        log.info("Iniciando rotación de clave maestra...")

        # 1. Backup de la clave actual
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = _BACKUP_DIR / f"anubis_master.key.{timestamp}.bak"
        try:
            shutil.copy2(_KEY_FILE, backup_path)
            self._aplicar_permisos(backup_path)
            log.info(f"Backup de clave anterior: {backup_path}")
        except OSError as e:
            log.error(f"No se pudo hacer backup de la clave: {e}")
            return False

        fernet_antigua = self._fernet

        # 2. Generar nueva clave
        try:
            nueva_clave = Fernet.generate_key()
            fernet_nueva = Fernet(nueva_clave)
            _KEY_FILE.write_bytes(nueva_clave)
            self._aplicar_permisos(_KEY_FILE)
        except OSError as e:
            log.error(f"No se pudo escribir la nueva clave: {e}")
            return False

        # 3. Re-cifrar archivos si se especificaron
        if archivos_cifrados:
            errores = 0
            for ruta in archivos_cifrados:
                archivo = Path(ruta)
                if not archivo.exists():
                    log.warning(
                        f"Archivo no encontrado durante rotación: {archivo}")
                    continue
                try:
                    datos_cifrados = archivo.read_bytes()
                    datos_planos = fernet_antigua.decrypt(datos_cifrados)
                    archivo.write_bytes(fernet_nueva.encrypt(datos_planos))
                    log.info(f"Re-cifrado con nueva clave: {archivo}")
                except InvalidToken:
                    log.error(
                        f"No se pudo descifrar {archivo} con la clave anterior.")
                    errores += 1
                except OSError as e:
                    log.error(f"Error de E/S al re-cifrar {archivo}: {e}")
                    errores += 1

            if errores:
                log.warning(f"Rotación completada con {errores} error(es).")

        self._fernet = fernet_nueva
        log.info("Rotación de clave completada.")
        return True

    # ── Estado ──────────────────────────────────────────────────────────

    def estado(self) -> dict:
        """Retorna información sobre el estado del módulo de seguridad."""
        return {
            "clave_cargada":  self._fernet is not None,
            "ruta_clave":     str(_KEY_FILE),
            "clave_existe":   _KEY_FILE.exists(),
            "backups":        len(list(_BACKUP_DIR.glob("*.bak"))),
        }
