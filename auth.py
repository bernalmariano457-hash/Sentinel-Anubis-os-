from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# ── bcrypt (opcional pero recomendado) ────────────────────────────────
try:
    import bcrypt
    _BCRYPT = True
except ImportError:
    _BCRYPT = False

log = logging.getLogger("sentinel.auth")

# ── Rutas de seguridad (relativas al directorio del proyecto) ─────────
_HERE = Path(__file__).resolve().parent
_CREDS_FILE = _HERE / "data" / "security" / \
    ".credentials"   # hash de contraseña
_LOCKOUT_FILE = _HERE / "data" / "security" / \
    ".lockout"      # bloqueo persistente

# ── Constantes configurables por entorno ──────────────────────────────
_BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", 12))
_MAX_INTENTOS = int(os.getenv("MAX_LOGIN_ATTEMPTS", 5))
_VENTANA_SEG = int(os.getenv("LOCKOUT_WINDOW_SECONDS", 300))  # 5 min


# ══════════════════════════════════════════════════════════════════════
# FUNCIONES DE HASHING
# ══════════════════════════════════════════════════════════════════════

def _hash_bcrypt(password: str) -> str:
    """Genera hash bcrypt con sal automática."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode()


def _hash_sha256_salted(password: str) -> str:
    """Hash SHA-256 con sal (fallback si bcrypt no está disponible)."""
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256s:{salt}:{h}"


def _hash(password: str) -> str:
    """Genera el hash más seguro disponible."""
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    return _hash_bcrypt(password) if _BCRYPT else _hash_sha256_salted(password)


def _verificar(password: str, almacenado: str) -> bool:
    """
    Verifica una contraseña contra su hash almacenado.
    Soporta tres formatos para compatibilidad:
      · bcrypt  → empieza con $2b$
      · sha256s → formato "sha256s:<salt>:<hash>"  (salted, seguro)
      · legacy  → 64 hex chars sin prefijo (SHA-256 sin sal, inseguro)
    """
    if not almacenado:
        return False

    # ── bcrypt ───────────────────────────────────────────────────────
    if almacenado.startswith("$2"):
        if not _BCRYPT:
            log.warning(
                "Hash bcrypt encontrado pero bcrypt no está instalado.")
            return False
        try:
            return bcrypt.checkpw(password.encode(), almacenado.encode())
        except Exception:
            return False

    # ── SHA-256 con sal ──────────────────────────────────────────────
    if almacenado.startswith("sha256s:"):
        try:
            _, salt, h = almacenado.split(":", 2)
            candidate = hashlib.sha256((salt + password).encode()).hexdigest()
            return hashlib.compare_digest(candidate, h)
        except Exception:
            return False

    # ── Hash legacy (SHA-256 sin sal, 64 hex) ────────────────────────
    if len(almacenado) == 64 and all(c in "0123456789abcdef" for c in almacenado):
        candidate = hashlib.sha256(password.encode()).hexdigest()
        return hashlib.compare_digest(candidate, almacenado)

    return False


def _es_legacy(almacenado: str) -> bool:
    """Detecta hashes inseguros que deben migrarse."""
    return (
        almacenado.startswith("sha256s:") or
        (len(almacenado) == 64 and ":" not in almacenado)
    )


# ══════════════════════════════════════════════════════════════════════
# CONTROL DE BLOQUEO PERSISTENTE
# ══════════════════════════════════════════════════════════════════════

class _LockoutManager:
    """
    Rastrea intentos fallidos en disco para que el bloqueo persista
    entre reinicios del sistema.
    """

    def __init__(self):
        _LOCKOUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _leer(self) -> dict:
        try:
            return json.loads(_LOCKOUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"intentos": [], "bloqueado_hasta": 0}

    def _escribir(self, data: dict) -> None:
        try:
            _LOCKOUT_FILE.write_text(json.dumps(data), encoding="utf-8")
            if sys.platform != "win32":
                _LOCKOUT_FILE.chmod(0o600)
        except OSError as e:
            log.error(f"No se pudo escribir archivo de bloqueo: {e}")

    def registrar_fallo(self) -> None:
        data = self._leer()
        now = time.time()
        # Mantener solo intentos dentro de la ventana
        data["intentos"] = [t for t in data["intentos"] if now - t < _VENTANA_SEG]
        data["intentos"].append(now)
        if len(data["intentos"]) >= _MAX_INTENTOS:
            data["bloqueado_hasta"] = now + _VENTANA_SEG
            log.warning("Sistema bloqueado por exceso de intentos fallidos.")
        self._escribir(data)

    def esta_bloqueado(self) -> tuple[bool, int]:
        """Retorna (bloqueado: bool, segundos_restantes: int)."""
        data = self._leer()
        restante = max(0, int(data.get("bloqueado_hasta", 0) - time.time()))
        return restante > 0, restante

    def reiniciar(self) -> None:
        self._escribir({"intentos": [], "bloqueado_hasta": 0})

    def intentos_restantes(self) -> int:
        data = self._leer()
        now = time.time()
        recientes = [t for t in data["intentos"] if now - t < _VENTANA_SEG]
        return max(0, _MAX_INTENTOS - len(recientes))


# ══════════════════════════════════════════════════════════════════════
# ALMACÉN DE CREDENCIALES
# ══════════════════════════════════════════════════════════════════════

class _CredentialStore:
    """
    Gestiona dónde y cómo se almacena el hash de contraseña.

    Prioridad de lectura:
      1. Variable de entorno  SENTINEL_PASSWORD_HASH
      2. Archivo              data/security/.credentials
      3. config.json          (legacy — se migra automáticamente)

    El hash NUNCA se escribe de vuelta en config.json.
    """

    def __init__(self, config: dict):
        self._config = config
        _CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)

    def leer(self) -> Optional[str]:
        # 1. Variable de entorno (máxima prioridad)
        env_hash = os.getenv("SENTINEL_PASSWORD_HASH")
        if env_hash:
            return env_hash.strip()

        # 2. Archivo de credenciales dedicado
        if _CREDS_FILE.exists():
            try:
                return _CREDS_FILE.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        # 3. Legacy: hash en config.json — migrar
        legacy = self._config.get("sistema", {}).get("password_hash")
        if legacy:
            log.info("Migrando password_hash desde config.json a .credentials")
            self.escribir(legacy)
            self._limpiar_config_json()
        return legacy

    def escribir(self, hash_str: str) -> None:
        """Guarda el hash en el archivo de credenciales con permisos restrictivos."""
        try:
            _CREDS_FILE.write_text(hash_str, encoding="utf-8")
            if sys.platform != "win32":
                _CREDS_FILE.chmod(0o600)
            log.info(f"Credenciales guardadas en {_CREDS_FILE}")
        except OSError as e:
            log.error(f"No se pudo guardar credenciales: {e}")

    def _limpiar_config_json(self) -> None:
        """Elimina password_hash de config.json si está presente."""
        sistema = self._config.get("sistema", {})
        if "password_hash" not in sistema:
            return
        del sistema["password_hash"]
        self._config.setdefault("sistema", {})["primer_arranque"] = False
        try:
            config_path = _HERE / "config.json"
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=4)
            if sys.platform != "win32":
                config_path.chmod(0o644)
            log.info("password_hash eliminado de config.json correctamente.")
        except OSError as e:
            log.warning(f"No se pudo actualizar config.json: {e}")

    def existe(self) -> bool:
        return bool(self.leer())


# ══════════════════════════════════════════════════════════════════════
# GESTOR DE AUTENTICACIÓN — API PÚBLICA
# ══════════════════════════════════════════════════════════════════════

class GestorAuth:
    """
    Módulo de autenticación de APEX SENTINEL.

    Interfaz compatible con la versión anterior:
        auth = GestorAuth(config, console, log)
        if not auth.solicitar_acceso():
            sys.exit(1)

    Mejoras respecto a la versión legacy:
        · bcrypt con sal (migración automática desde SHA-256)
        · Hash almacenado en .credentials, no en config.json
        · Bloqueo persistente entre sesiones
        · Migración automática de hashes inseguros al autenticar
    """

    def __init__(self, config: dict, console: Console, log_sistema):
        self.config = config
        self.console = console
        self.log = log_sistema
        self._creds = _CredentialStore(config)
        self._lockout = _LockoutManager()

    # ── Hashing (API pública para uso interno) ─────────────────────────

    @staticmethod
    def generar_hash(password: str) -> str:
        """Genera un hash seguro para una contraseña. Útil para scripts de setup."""
        return _hash(password)

    # ── Flujo de configuración inicial ────────────────────────────────

    def configurar_primera_vez(self) -> str:
        """
        Solicita y confirma la contraseña maestra en el primer arranque.
        Retorna el hash generado (ya guardado en .credentials).
        """
        self.console.print(Panel(
            "[bold cyan]ANUBIS OS — SETUP DE SEGURIDAD[/bold cyan]\n"
            "[white]No se detectó clave de operador.\n"
            "Configure su acceso maestro.[/white]\n\n"
            f"[dim]Hash almacenado en:[/dim] [white]{_CREDS_FILE}[/white]",
            border_style="cyan",
            title="[bold]PRIMERA CONFIGURACIÓN[/bold]",
        ))
        while True:
            nueva = Prompt.ask(
                "[?] Contraseña Maestra [dim](mín. 8 caracteres)[/dim]",
                password=True,
            )
            if len(nueva) < 8:
                self.console.print(
                    "[red][!] Contraseña demasiado corta (mínimo 8 caracteres).[/red]")
                continue

            confirmar = Prompt.ask("[?] Confirme su contraseña", password=True)
            if nueva != confirmar:
                self.console.print(
                    "[red][!] Las claves no coinciden. Intente de nuevo.[/red]")
                continue

            h = _hash(nueva)
            self._creds.escribir(h)

            # Asegurarse de que config.json quede limpio
            self._creds._limpiar_config_json()

            modo = "bcrypt" if _BCRYPT else "SHA-256 con sal"
            self.console.print(
                f"[green][+] Acceso configurado correctamente ({modo}).[/green]"
            )
            self.log.success("Contraseña maestra configurada.", "GestorAuth")
            time.sleep(0.8)
            return h

    # ── Login ──────────────────────────────────────────────────────────

    def solicitar_acceso(self) -> bool:
        """
        Solicita credenciales al operador.
        Retorna True si el acceso fue concedido, False si se bloqueó.
        """
        # ── Primer arranque ───────────────────────────────────────────
        primer_arranque = self.config.get(
            "sistema", {}).get("primer_arranque", True)
        if primer_arranque or not self._creds.existe():
            self.configurar_primera_vez()
            self.config.setdefault("sistema", {})["primer_arranque"] = False
            return True

        # ── Verificar bloqueo persistente ─────────────────────────────
        bloqueado, restante = self._lockout.esta_bloqueado()
        if bloqueado:
            mins = restante // 60
            segs = restante % 60
            self.console.print(Panel(
                f"[bold red]⛔ SISTEMA BLOQUEADO[/bold red]\n\n"
                f"Demasiados intentos fallidos.\n"
                f"Intenta de nuevo en [bold]{mins}m {segs}s[/bold].",
                border_style="red",
            ))
            self.log.warning(
                f"Intento de acceso durante bloqueo activo ({restante}s restantes).",
                "GestorAuth",
            )
            return False

        # ── Pantalla de login ─────────────────────────────────────────
        hash_almacenado = self._creds.leer()

        self.console.print(
            f"\n[bold white]{'─'*44}[/bold white]\n"
            f"[bold green]    APEX SENTINEL — ANUBIS OS · LOGIN[/bold green]\n"
            f"[bold white]{'─'*44}[/bold white]\n"
        )

        restantes = self._lockout.intentos_restantes()

        while restantes > 0:
            entrada = Prompt.ask(
                f"[?] Clave de acceso "
                f"[dim]({restantes} intento{'s' if restantes > 1 else ''})[/dim]",
                password=True,
            )

            if _verificar(entrada, hash_almacenado):
                self._lockout.reiniciar()
                self._migrar_hash_si_necesario(entrada, hash_almacenado)
                self.log.success("Acceso concedido.", "GestorAuth")
                return True

            self._lockout.registrar_fallo()
            restantes = self._lockout.intentos_restantes()

            bloqueado, restante = self._lockout.esta_bloqueado()
            if bloqueado:
                mins = restante // 60
                self.console.print(
                    f"[bold red][!] Sistema bloqueado por {mins} minuto(s).[/bold red]"
                )
                self.log.warning(
                    "Sistema bloqueado por exceso de intentos.", "GestorAuth"
                )
                return False

            self.console.print(
                f"[red][!] Clave incorrecta.[/red] "
                f"[dim]({restantes} intento{'s' if restantes > 1 else ''} restante{'s' if restantes > 1 else ''})[/dim]"
            )

        self.log.warning("Acceso denegado: intentos agotados.", "GestorAuth")
        return False

    # ── Cambio de contraseña ───────────────────────────────────────────

    def cambiar_password(self, actual: str, nueva: str) -> bool:
        """
        Cambia la contraseña verificando la actual.
        Retorna True si se cambió correctamente.
        """
        hash_actual = self._creds.leer()
        if not _verificar(actual, hash_actual):
            self.log.warning(
                "Intento de cambio de contraseña fallido.", "GestorAuth")
            return False
        if len(nueva) < 8:
            raise ValueError(
                "La nueva contraseña debe tener al menos 8 caracteres.")
        self._creds.escribir(_hash(nueva))
        self.log.success("Contraseña actualizada correctamente.", "GestorAuth")
        return True

    # ── Migración automática de hashes inseguros ───────────────────────

    def _migrar_hash_si_necesario(self, password: str, hash_actual: str) -> None:
        """
        Después de un login exitoso, si el hash es SHA-256 (legacy o con sal),
        lo migra silenciosamente a bcrypt.
        """
        if not _BCRYPT:
            return
        if not _es_legacy(hash_actual):
            return
        nuevo_hash = _hash_bcrypt(password)
        self._creds.escribir(nuevo_hash)
        log.info("Hash de contraseña migrado de SHA-256 a bcrypt automáticamente.")
