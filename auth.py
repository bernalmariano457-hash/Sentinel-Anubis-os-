import os
import sys
import json
import time
import hashlib

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

try:
    import bcrypt
    BCRYPT_OK = True
except ImportError:
    BCRYPT_OK = False


class GestorAuth:
    """
    Gestiona autenticación por contraseña maestra con soporte bcrypt.
    Si bcrypt no está disponible, cae a SHA-256 con salt.
    """

    MAX_INTENTOS = 3
    CONFIG_PATH = "config.json"

    def __init__(self, config: dict, console: Console, log):
        self.config = config
        self.console = console
        self.log = log

    # ── Hashing ────────────────────────────────────────────────────────

    def _hash(self, password: str) -> str:
        if BCRYPT_OK:
            return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        salt = os.urandom(16).hex()
        h = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"{salt}:{h}"

    def _verificar(self, password: str, almacenado: str) -> bool:
        # Compatibilidad con hashes legacy (SHA-256 sin salt, 64 hex chars)
        if len(almacenado) == 64 and ":" not in almacenado:
            return hashlib.sha256(password.encode()).hexdigest() == almacenado

        if BCRYPT_OK:
            try:
                return bcrypt.checkpw(password.encode(), almacenado.encode())
            except Exception:
                pass

        # SHA-256 con salt (salt:hash)
        try:
            salt, h = almacenado.split(":", 1)
            return hashlib.sha256((salt + password).encode()).hexdigest() == h
        except Exception:
            return False

    # ── Persistencia ───────────────────────────────────────────────────

    def _guardar_config(self) -> None:
        try:
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
            # Permisos restrictivos en sistemas POSIX
            if sys.platform != "win32":
                os.chmod(self.CONFIG_PATH, 0o600)
        except OSError as e:
            self.log.error(
                f"No se pudo guardar {self.CONFIG_PATH}: {e}", "GestorAuth")

    # ── API pública ────────────────────────────────────────────────────

    def configurar_primera_vez(self) -> str:
        """Flujo de configuración inicial: solicita y confirma la contraseña maestra."""
        self.console.print(Panel(
            "[bold cyan]ANUBIS OS: SETUP DE SEGURIDAD[/bold cyan]\n"
            "[white]No se detectó clave de operador. Configure su acceso maestro.[/white]",
            border_style="cyan"
        ))
        while True:
            nueva = Prompt.ask(
                "[?] Contraseña Maestra (mín. 8 caracteres)", password=True)
            if len(nueva) < 8:
                self.console.print(
                    "[red][!] Contraseña demasiado débil (mínimo 8 caracteres).[/red]")
                continue
            confirmar = Prompt.ask("[?] Confirme su Contraseña", password=True)
            if nueva != confirmar:
                self.console.print(
                    "[red][!] Las claves no coinciden. Intente de nuevo.[/red]")
                continue
            h = self._hash(nueva)
            self.console.print(
                "[green][+] Acceso configurado correctamente. Iniciando...[/green]")
            self.log.success("Contraseña maestra configurada.", "GestorAuth")
            time.sleep(1)
            return h

    def solicitar_acceso(self) -> bool:
        """
        Solicita credenciales al operador.
        Retorna True si el acceso fue concedido, False si se agotaron los intentos.
        """
        hash_almacenado = self.config["sistema"].get("password_hash")

        if not hash_almacenado or self.config["sistema"].get("primer_arranque", True):
            nuevo_hash = self.configurar_primera_vez()
            self.config["sistema"]["password_hash"] = nuevo_hash
            self.config["sistema"]["primer_arranque"] = False
            self._guardar_config()
            return True

        self.console.print(
            f"\n[bold white]{'─'*40}[/bold white]\n"
            f"[bold green]  APEX SENTINEL — LOGIN[/bold green]\n"
            f"[bold white]{'─'*40}[/bold white]\n"
        )

        for intento in range(self.MAX_INTENTOS, 0, -1):
            entrada = Prompt.ask(
                f"[?] Clave de acceso ([dim]{intento} intento{'s' if intento > 1 else ''}[/dim])",
                password=True
            )
            if self._verificar(entrada, hash_almacenado):
                self.log.success("Acceso concedido.", "GestorAuth")
                return True
            self.console.print("[red][!] Clave incorrecta.[/red]")

        self.log.warning(
            "Acceso denegado: máximo de intentos alcanzado.", "GestorAuth")
        return False
