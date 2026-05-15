from __future__ import annotations

import os
import zlib
from Crypto.Cipher import AES


class WhatsAppDecryptor:
    def __init__(self):
        pass

    def descifrar_crypt14(self, crypt_file, key_file, output_file):
        print(f"\n[*] Iniciando secuencia de descifrado AES-GCM...")

        try:
            # 1. Leer el archivo de la llave (Debe ser exactamente de 158 bytes)
            with open(key_file, 'rb') as kf:
                key_data = kf.read()

            if len(key_data) != 158:
                print(
                    "\033[1;31m[-] Error: El archivo key es inválido (no tiene 158 bytes).\033[0m")
                return False

            # La llave AES-256 real está escondida entre el byte 30 y el 61
            aes_key = key_data[30:62]
            print("[+] Llave AES-256 extraída del Enclave.")

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
            print("[*] Inyectando Vector de Inicialización (IV) y descifrando...")
            cipher = AES.new(aes_key, AES.MODE_GCM, iv)
            decrypted_data = cipher.decrypt_and_verify(ciphertext, auth_tag)

            # 4. WhatsApp comprime los datos para ahorrar espacio. Hay que descomprimirlos.
            print("[*] Descomprimiendo SQLite interno (zlib)...")
            uncompressed_data = zlib.decompress(decrypted_data)

            # 5. Guardar la base de datos pura y legible
            with open(output_file, 'wb') as outf:
                outf.write(uncompressed_data)

            print(
                f"\033[1;32m[+] ÉXITO: Base de datos limpia guardada en: {output_file}\033[0m")
            return True

        except ValueError:
            print(
                "\033[1;31m[-] FALLO: El Auth Tag no coincide. ¿La llave no pertenece a esta base de datos?\033[0m")
            return False
        except Exception as e:
            print(f"\033[1;31m[-] Error crítico en descifrado: {e}\033[0m")
            return False
