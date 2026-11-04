from __future__ import annotations

import zlib
from pathlib import Path

from Crypto.Cipher import AES

from core.evidence_bridge import register_evidence


class WhatsAppDecryptor:
    def __init__(self, sentinel=None):
        from rich.console import Console
        self.console = Console()
        self.sentinel = sentinel
        self.workspace = getattr(
            sentinel, "workspace", Path.cwd()) if sentinel else Path.cwd()
        self.operator_id = getattr(
            sentinel, "operator_id", "op-mariano") if sentinel else "op-mariano"

    def _registrar_log(self, mensaje: str):
        if self.sentinel and hasattr(self.sentinel, "reportes"):
            self.sentinel.reportes.registrar_evento("FORENSE", mensaje)
        else:
            self.console.print(f"[dim][LOG] {mensaje}[/dim]")

    def descifrar_crypt14(self, crypt_file: str | Path, key_file: str | Path, output_file: str | Path) -> bool:
        self.console.print(
            "\n[cyan][*] Iniciando secuencia de descifrado AES-GCM...[/cyan]")

        crypt_path = Path(crypt_file)
        key_path = Path(key_file)
        output_path = Path(output_file)

        if not crypt_path.exists():
            self.console.print(
                f"[red][-] Archivo .crypt14 no encontrado: {crypt_path}[/red]")
            return False
        if not key_path.exists():
            self.console.print(
                f"[red][-] Archivo de clave no encontrado: {key_path}[/red]")
            return False
        if output_path.exists():
            self.console.print(
                f"[red][-] El archivo de salida ya existe (evitando sobrescribir evidencia): {output_path}[/red]")
            return False

        try:
            with open(key_path, 'rb') as kf:
                key_data = kf.read()

            if len(key_data) != 158:
                self.console.print(
                    "[red][-] El archivo key es inválido (no tiene 158 bytes).[/red]")
                return False

            aes_key = key_data[30:62]
            self.console.print(
                "[green][+] Llave AES-256 extraída del Enclave.[/green]")

            with open(crypt_path, 'rb') as cf:
                crypt_data = cf.read()

            iv = crypt_data[67:83]
            ciphertext_with_tag = crypt_data[83:]
            ciphertext = ciphertext_with_tag[:-16]
            auth_tag = ciphertext_with_tag[-16:]

            self.console.print(
                "[cyan][*] Inyectando IV y descifrando...[/cyan]")
            cipher = AES.new(aes_key, AES.MODE_GCM, iv)
            decrypted_data = cipher.decrypt_and_verify(ciphertext, auth_tag)

            self.console.print(
                "[cyan][*] Descomprimiendo SQLite interno (zlib)...[/cyan]")
            uncompressed_data = zlib.decompress(decrypted_data)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as outf:
                outf.write(uncompressed_data)

            self.console.print(
                f"[green][+] Base de datos limpia guardada en: {output_path}[/green]")

            self.console.print(
                "[cyan][*] Registrando evidencia en cadena de custodia...[/cyan]")

            register_evidence(
                workspace=self.workspace,
                operator_id=self.operator_id,
                artifact_path=crypt_path,
                artifact_type="whatsapp_crypt14",
                details={"description": "Archivo .crypt14 original",
                         "output_db": str(output_path.name)}
            )

            register_evidence(
                workspace=self.workspace,
                operator_id=self.operator_id,
                artifact_path=key_path,
                artifact_type="whatsapp_key",
                details={"description": "Archivo de clave de 158 bytes"}
            )

            register_evidence(
                workspace=self.workspace,
                operator_id=self.operator_id,
                artifact_path=output_path,
                artifact_type="whatsapp_sqlite",
                details={
                    "description": "Base de datos SQLite descifrada y descomprimida"}
            )

            self._registrar_log(
                f"Base de datos WhatsApp descifrada: {output_path.name}")
            self.console.print(
                "[bold green][+] Evidencia firmada y registrada en custodia.[/bold green]")

            return True

        except ValueError:
            self.console.print(
                "[red][-] FALLO: Auth Tag no coincide. ¿Llave incorrecta?[/red]")
            self._registrar_log(
                "Fallo de descifrado WhatsApp: Auth Tag inválido.")
            return False
        except Exception as e:
            self.console.print(
                f"[red][-] Error crítico en descifrado: {e}[/red]")
            self._registrar_log(f"Fallo de descifrado WhatsApp: {e}")
            return False
