from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.Security import SecurityModule
    from core.log_sistema import LogSistema


# Extensiones de archivos que se protegen en el protocolo de pánico
_EXTENSIONES_PROTEGIDAS = {
    ".json", ".jsonl", ".log", ".txt", ".md",
    ".pcap", ".cap", ".pcapng",
    ".csv", ".iq", ".wav", ".db", ".sqlite",
}

# Directorios que incluye el protocolo de pánico
_DIRS_PANICO = [
    Path("data/logs"),
    Path("data/evidence"),
    Path("data/proyectos"),
    Path("core/data/logs"),
]


class SentinelRecovery:

    def __init__(
        self,
        security: "SecurityModule",
        log: "LogSistema | None" = None,
    ) -> None:
        if security is None:
            raise ValueError(
                "SentinelRecovery requiere un SecurityModule inicializado. "
                "Asegúrate de que sentinel.security no sea None."
            )
        self._sec = security
        self._log = log

    # ── Logging interno ───────────────────────────────────────────────

    def _info(self, msg: str) -> None:
        if self._log:
            self._log.info(msg, "Recovery")
        else:
            print(f"  [*] {msg}")

    def _warn(self, msg: str) -> None:
        if self._log:
            self._log.warning(msg, "Recovery")
        else:
            print(f"  [!] {msg}")

    def _error(self, msg: str) -> None:
        if self._log:
            self._log.error(msg, "Recovery")
        else:
            print(f"  [ERROR] {msg}")

    # ── Descubrir archivos ────────────────────────────────────────────

    def _archivos_en_dirs(self, dirs: list[Path]) -> list[Path]:
        encontrados: list[Path] = []
        for d in dirs:
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if f.is_file() and f.suffix.lower() in _EXTENSIONES_PROTEGIDAS:
                    encontrados.append(f)
        return encontrados

    # ── Borrado seguro ────────────────────────────────────────────────

    @staticmethod
    def _borrar_seguro(ruta: Path) -> bool:

        try:
            size = ruta.stat().st_size
            if size > 0:
                ruta.write_bytes(secrets.token_bytes(size))
            ruta.unlink()
            return True
        except OSError as e:
            return False

    # ── API pública ───────────────────────────────────────────────────

    def ejecutar_panico(self, confirmar: bool = False) -> dict:

        archivos = self._archivos_en_dirs(_DIRS_PANICO)

        if not confirmar:
            self._warn(
                f"[DRY-RUN] Se cifrarían {len(archivos)} archivos. "
                "Llama con confirmar=True para ejecutar."
            )
            return {
                "cifrados": 0,
                "errores": 0,
                "archivos": [str(f) for f in archivos],
                "dry_run": True,
            }

        self._warn(f"PÁNICO activado — cifrando {len(archivos)} archivos...")
        cifrados = 0
        errores = 0

        for archivo in archivos:
            ok = self._sec.encriptar_archivo(archivo)
            if ok:
                cifrados += 1
                self._info(f"Cifrado: {archivo}")
            else:
                errores += 1
                self._error(f"Fallo al cifrar: {archivo}")
            time.sleep(0.01)  # no saturar I/O en CM4

        self._info(
            f"Pánico completado: {cifrados} cifrados, {errores} errores."
        )
        return {
            "cifrados": cifrados,
            "errores": errores,
            "archivos": [str(f) for f in archivos],
            "dry_run": False,
        }

    def ejecutar_rescate(
        self,
        archivos: list[str | Path] | None = None,
    ) -> dict:

        if archivos is None:
            rutas = self._archivos_en_dirs(_DIRS_PANICO)
            self._info(
                f"Rescate automático: {len(rutas)} archivos encontrados."
            )
        else:
            rutas = [Path(f) for f in archivos]

        descifrados = 0
        errores = 0

        for archivo in rutas:
            if not archivo.exists():
                self._warn(f"No encontrado: {archivo}")
                continue
            ok = self._sec.desencriptar_archivo(archivo)
            if ok:
                descifrados += 1
                self._info(f"Restaurado: {archivo}")
            else:
                errores += 1
                self._error(
                    f"Fallo al descifrar: {archivo}. "
                    "¿Archivo no estaba cifrado o clave incorrecta?"
                )

        self._info(
            f"Rescate completado: {descifrados} restaurados, {errores} errores."
        )
        return {"descifrados": descifrados, "errores": errores}

    def borrado_emergencia(
        self,
        dirs_extra: list[Path] | None = None,
        confirmar: bool = False,
    ) -> dict:
        dirs = _DIRS_PANICO + (dirs_extra or [])
        archivos = self._archivos_en_dirs(dirs)

        if not confirmar:
            self._warn(
                f"[DRY-RUN] Se eliminarían {len(archivos)} archivos. "
                "Pasar confirmar=True para ejecutar. IRREVERSIBLE."
            )
            return {
                "eliminados": 0,
                "errores": 0,
                "archivos": [str(f) for f in archivos],
                "dry_run": True,
            }

        self._warn(
            f"BORRADO DE EMERGENCIA — eliminando {len(archivos)} archivos..."
        )
        eliminados = 0
        errores = 0

        for archivo in archivos:
            ok = self._borrar_seguro(archivo)
            if ok:
                eliminados += 1
            else:
                errores += 1
                self._error(f"No se pudo eliminar: {archivo}")

        # Borrar también la clave maestra (sin clave, los cifrados son ilegibles)
        try:
            from core.Security import _KEY_FILE
            if _KEY_FILE.exists():
                self._borrar_seguro(_KEY_FILE)
                self._warn("Clave maestra eliminada.")
        except Exception:
            pass

        self._warn(
            f"Borrado completado: {eliminados} eliminados, {errores} errores."
        )
        return {
            "eliminados": eliminados,
            "errores": errores,
            "dry_run": False,
        }

    def estado_cifrado(self) -> dict:
        from cryptography.fernet import InvalidToken

        archivos = self._archivos_en_dirs(_DIRS_PANICO)
        cifrados: list[str] = []
        sin_cifrar: list[str] = []

        for archivo in archivos:
            try:
                datos = archivo.read_bytes()
                # Intentar descifrar en memoria (sin escribir)
                self._sec._fernet.decrypt(datos)
                # Si no lanza excepción, está cifrado
                cifrados.append(str(archivo))
            except InvalidToken:
                # No es un token Fernet válido → sin cifrar
                sin_cifrar.append(str(archivo))
            except Exception:
                sin_cifrar.append(str(archivo))

        return {
            "cifrados": cifrados,
            "sin_cifrar": sin_cifrar,
            "total": len(archivos),
        }


# ── Punto de entrada standalone (uso en terminal) ─────────────────────

if __name__ == "__main__":
    import sys
    from core.Security import SecurityModule

    class _MockSentinel:
        pass

    print("\n[+] PROTOCOLO DE RECUPERACIÓN STANDALONE")
    print("    Inicializando SecurityModule...")

    try:
        sec = SecurityModule(_MockSentinel())
        recovery = SentinelRecovery(sec)

        if len(sys.argv) > 1 and sys.argv[1] == "--rescate":
            resultado = recovery.ejecutar_rescate()
            print(f"\n[+] Restaurados: {resultado['descifrados']}")
            print(f"[-] Errores:     {resultado['errores']}")
        else:
            print("\n  Uso: python Recovery.py --rescate")
            print("  O importa SentinelRecovery desde tu código.")
    except Exception as e:
        print(f"[-] Error: {e}")
