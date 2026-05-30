from __future__ import annotations

import os
import zlib
from Crypto.Cipher import AES


class WhatsAppDecryptor:
    def __init__(self):
        from rich.console import Console
        self.console = Console()

    def descifrar_crypt14(self, crypt_file, key_file, output_file):
        self.console.print("\n[cyan][*] Iniciando secuencia de descifrado AES-GCM...[/cyan]")

        try:
            # 1. Leer el archivo de la llave (Debe ser exactamente de 158 bytes)
            with open(key_file, 'rb') as kf:
                key_data = kf.read()

            if len(key_data) != 158:
                self.console.print("[red][-] El archivo key es inválido (no tiene 158 bytes).[/red]")
                return False

            # La llave AES-256 real está escondida entre el byte 30 y el 61
            aes_key = key_data[30:62]
            self.console.print("[green][+] Llave AES-256 extraída del Enclave.[/green]")

            # 2. Leer la base de datos cifrada (msgstore.db.crypt14)
            with open(crypt_file, 'rb') as cf:
                crypt_data = cf.read()

            # Estructura forense del archivo .crypt14:
            # Header (67 bytes) | IV (16 bytes) | Texto Cifrado | Auth Tag (16 bytes finales)
            iv = crypt_data[67:83]
            ciphertext_with_tag = crypt_data[83:]

            ciphertext = ciphertext_with_tag[:-16]
            auth_tag = ciphertext_with_tag[-16:]

            # 3. Aplicar la matemática de descifrado
            self.console.print("[cyan][*] Inyectando IV y descifrando...[/cyan]")
            cipher = AES.new(aes_key, AES.MODE_GCM, iv)
            decrypted_data = cipher.decrypt_and_verify(ciphertext, auth_tag)

            # 4. WhatsApp comprime los datos para ahorrar espacio. Hay que descomprimirlos.
            self.console.print("[cyan][*] Descomprimiendo SQLite interno (zlib)...[/cyan]")
            uncompressed_data = zlib.decompress(decrypted_data)

            # 5. Guardar la base de datos pura y legible
            with open(output_file, 'wb') as outf:
                outf.write(uncompressed_data)

            self.console.print(f"[green][+] Base de datos limpia guardada en: {output_file}[/green]")
            return True

        except ValueError:
            self.console.print("[red][-] FALLO: Auth Tag no coincide. ¿Llave incorrecta?[/red]")
            return False
        except Exception as e:
            self.console.print(f"[red][-] Error crítico en descifrado: {e}[/red]")
            return False
