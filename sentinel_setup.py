"""
╔══════════════════════════════════════════════════════════════════╗
║  APEX SENTINEL — sentinel_setup.py                               ║
║  Utilidad de configuración inicial de credenciales               ║
╠══════════════════════════════════════════════════════════════════╣
╚══════════════════════════════════════════════════════════════════╝
"""
import argparse
import getpass
import json
import os
import sys
from pathlib import Path

# Asegurar que el directorio del proyecto esté en el path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

try:
    import bcrypt
    _BCRYPT = True
except ImportError:
    _BCRYPT = False

_CREDS_FILE = _HERE / "data" / "security" / ".credentials"
_CONFIG_FILE = _HERE / "config.json"


def _hash(password: str) -> str:
    if _BCRYPT:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
    import hashlib
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256s:{salt}:{h}"


def setup_credenciales(forzar: bool = False) -> None:
    _CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _CREDS_FILE.exists() and not forzar:
        print(f"[i] Ya existen credenciales en {_CREDS_FILE}")
        resp = input("[?] ¿Desea sobreescribirlas? (s/N): ").strip().lower()
        if resp != "s":
            print("[·] Operación cancelada.")
            return

    print("\n── CONFIGURACIÓN DE CONTRASEÑA MAESTRA ──")
    modo = "bcrypt (seguro)" if _BCRYPT else "SHA-256 con sal (instala bcrypt para mayor seguridad)"
    print(f"[·] Modo de hash: {modo}\n")

    while True:
        password = getpass.getpass(
            "[?] Nueva contraseña maestra (mín. 8 caracteres): ")
        if len(password) < 8:
            print("[!] Contraseña demasiado corta.\n")
            continue
        confirmar = getpass.getpass("[?] Confirme la contraseña: ")
        if password != confirmar:
            print("[!] Las contraseñas no coinciden.\n")
            continue
        break

    hash_str = _hash(password)
    _CREDS_FILE.write_text(hash_str, encoding="utf-8")
    if sys.platform != "win32":
        _CREDS_FILE.chmod(0o600)

    # Limpiar config.json si tiene password_hash
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        sistema = config.get("sistema", {})
        if "password_hash" in sistema:
            del sistema["password_hash"]
            sistema["primer_arranque"] = False
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            print("[+] password_hash eliminado de config.json")

    print(f"\n[✓] Credenciales guardadas en: {_CREDS_FILE}")
    print("[✓] Configuración completada. Puedes iniciar Sentinel.\n")


def verificar_integridad() -> None:
    print("\n── VERIFICACIÓN DE INTEGRIDAD ──\n")

    # Credenciales
    if _CREDS_FILE.exists():
        contenido = _CREDS_FILE.read_text().strip()
        if contenido.startswith("$2"):
            tipo = "bcrypt ✓"
        elif contenido.startswith("sha256s:"):
            tipo = "SHA-256 con sal (seguro, pero actualiza a bcrypt)"
        elif len(contenido) == 64:
            tipo = "⚠ SHA-256 SIN SAL — VULNERABLE, ejecuta --reset"
        else:
            tipo = "? Formato desconocido"
        print(f"  [✓] Credenciales: {_CREDS_FILE}")
        print(f"      Tipo de hash: {tipo}")
    else:
        print(f"  [!] Sin credenciales. Ejecuta: python sentinel_setup.py")

    # config.json
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        if "password_hash" in config.get("sistema", {}):
            print(
                "  [⚠] config.json contiene password_hash — elimínalo o ejecuta --reset")
        else:
            print("  [✓] config.json limpio (sin credenciales)")
    else:
        print("  [!] config.json no encontrado")

    # bcrypt
    print(f"  {'[✓]' if _BCRYPT else '[!]'} bcrypt {'disponible' if _BCRYPT else 'NO disponible — pip install bcrypt'}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sentinel — Configuración de seguridad")
    parser.add_argument("--reset",  action="store_true",
                        help="Forzar nueva contraseña")
    parser.add_argument("--check",  action="store_true",
                        help="Verificar integridad de configuración")
    args = parser.parse_args()

    if args.check:
        verificar_integridad()
    else:
        setup_credenciales(forzar=args.reset)
