import time


class DuckyModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.hid_path = "/dev/hidg0"
        # Mapa de teclas HID (Keyboard Scan Codes)
        self.MAPA = {
            'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09,
            'g': 0x0a, 'h': 0x0b, 'i': 0x0c, 'j': 0x0d, 'k': 0x0e, 'l': 0x0f,
            'm': 0x10, 'n': 0x11, 'o': 0x12, 'p': 0x13, 'q': 0x14, 'r': 0x15,
            's': 0x16, 't': 0x17, 'u': 0x18, 'v': 0x19, 'w': 0x1a, 'x': 0x1b,
            'y': 0x1c, 'z': 0x1d, '1': 0x1e, '2': 0x1f, '3': 0x20, '4': 0x21,
            '5': 0x22, '6': 0x23, '7': 0x24, '8': 0x25, '9': 0x26, '0': 0x27,
            'ENTER': 0x28, 'ESC': 0x29, 'BACKSPACE': 0x2a, 'TAB': 0x2b, 'SPACE': 0x2c,
            '.': 0x37, ':': 0x33, '/': 0x38
        }

    def presionar(self, key_code, modifier=0x00):
        """Envía el código de la tecla al dispositivo HID"""
        try:
            with open(self.hid_path, 'rb+') as fd:
                # Reporte de 8 bytes: [Modificador, Reservado, Tecla1, ...]
                reporte = bytearray(8)
                reporte[0] = modifier  # Shift, Ctrl, Alt...
                reporte[2] = key_code
                fd.write(reporte)
                # Soltar tecla (limpiar reporte)
                fd.write(bytearray(8))
        except Exception as e:
            print(f"[!] Error HID: {e}")

    def escribir_texto(self, texto):
        for char in texto.lower():
            if char in self.MAPA:
                self.presionar(self.MAPA[char])
                time.sleep(0.01)  # Pequeña pausa para no saturar
            elif char == " ":
                self.presionar(self.MAPA['SPACE'])

    def ejecutar_script(self, ruta_script):
        try:
            with open(ruta_script, "r") as f:
                lineas = f.readlines()

            print(f"[{self.sentinel.nombre}] Ejecutando Ducky Script...")
            for linea in lineas:
                partes = linea.strip().split(" ", 1)
                comando = partes[0]

                if comando == "STRING":
                    self.escribir_texto(partes[1])
                elif comando == "DELAY":
                    time.sleep(int(partes[1]) / 1000)
                elif comando == "ENTER":
                    self.presionar(self.MAPA['ENTER'])
                elif comando == "GUI" or comando == "WINDOWS":
                    # 0x08 es la tecla Windows/Meta
                    self.presionar(0x00, 0x08)
            print("[OK] Script finalizado.")
        except Exception as e:
            print(f"[!] Error en script: {e}")
