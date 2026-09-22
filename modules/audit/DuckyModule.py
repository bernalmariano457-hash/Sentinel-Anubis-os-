from __future__ import annotations

import time
import logging

logger = logging.getLogger(__name__)

MOD_NONE = 0x00
MOD_CTRL = 0x01
MOD_SHIFT = 0x02
MOD_ALT = 0x04
MOD_GUI = 0x08

_BASE = {
    'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09,
    'g': 0x0a, 'h': 0x0b, 'i': 0x0c, 'j': 0x0d, 'k': 0x0e, 'l': 0x0f,
    'm': 0x10, 'n': 0x11, 'o': 0x12, 'p': 0x13, 'q': 0x14, 'r': 0x15,
    's': 0x16, 't': 0x17, 'u': 0x18, 'v': 0x19, 'w': 0x1a, 'x': 0x1b,
    'y': 0x1c, 'z': 0x1d,
    '1': 0x1e, '2': 0x1f, '3': 0x20, '4': 0x21, '5': 0x22,
    '6': 0x23, '7': 0x24, '8': 0x25, '9': 0x26, '0': 0x27,
    'ENTER': 0x28, 'ESC': 0x29, 'BACKSPACE': 0x2a, 'TAB': 0x2b, 'SPACE': 0x2c,
    '-': 0x2d, '=': 0x2e, '[': 0x2f, ']': 0x30, '\\': 0x31,
    ';': 0x33, "'": 0x34, '`': 0x35, ',': 0x36, '.': 0x37, '/': 0x38,
    'F1': 0x3a, 'F2': 0x3b, 'F3': 0x3c, 'F4': 0x3d, 'F5': 0x3e,
    'F6': 0x3f, 'F7': 0x40, 'F8': 0x41, 'F9': 0x42, 'F10': 0x43,
    'F11': 0x44, 'F12': 0x45,
    'DELETE': 0x4c, 'HOME': 0x4a, 'END': 0x4d,
    'PAGEUP': 0x4b, 'PAGEDOWN': 0x4e,
    'UP': 0x52, 'DOWN': 0x51, 'LEFT': 0x50, 'RIGHT': 0x4f,
}

_SHIFT_MAP = {
    'A': (_BASE['a'], MOD_SHIFT), 'B': (_BASE['b'], MOD_SHIFT),
    'C': (_BASE['c'], MOD_SHIFT), 'D': (_BASE['d'], MOD_SHIFT),
    'E': (_BASE['e'], MOD_SHIFT), 'F': (_BASE['f'], MOD_SHIFT),
    'G': (_BASE['g'], MOD_SHIFT), 'H': (_BASE['h'], MOD_SHIFT),
    'I': (_BASE['i'], MOD_SHIFT), 'J': (_BASE['j'], MOD_SHIFT),
    'K': (_BASE['k'], MOD_SHIFT), 'L': (_BASE['l'], MOD_SHIFT),
    'M': (_BASE['m'], MOD_SHIFT), 'N': (_BASE['n'], MOD_SHIFT),
    'O': (_BASE['o'], MOD_SHIFT), 'P': (_BASE['p'], MOD_SHIFT),
    'Q': (_BASE['q'], MOD_SHIFT), 'R': (_BASE['r'], MOD_SHIFT),
    'S': (_BASE['s'], MOD_SHIFT), 'T': (_BASE['t'], MOD_SHIFT),
    'U': (_BASE['u'], MOD_SHIFT), 'V': (_BASE['v'], MOD_SHIFT),
    'W': (_BASE['w'], MOD_SHIFT), 'X': (_BASE['x'], MOD_SHIFT),
    'Y': (_BASE['y'], MOD_SHIFT), 'Z': (_BASE['z'], MOD_SHIFT),
    '!': (_BASE['1'], MOD_SHIFT), '@': (_BASE['2'], MOD_SHIFT),
    '#': (_BASE['3'], MOD_SHIFT), '$': (_BASE['4'], MOD_SHIFT),
    '%': (_BASE['5'], MOD_SHIFT), '^': (_BASE['6'], MOD_SHIFT),
    '&': (_BASE['7'], MOD_SHIFT), '*': (_BASE['8'], MOD_SHIFT),
    '(': (_BASE['9'], MOD_SHIFT), ')': (_BASE['0'], MOD_SHIFT),
    '_': (_BASE['-'], MOD_SHIFT), '+': (_BASE['='], MOD_SHIFT),
    '{': (_BASE['['], MOD_SHIFT), '}': (_BASE[']'], MOD_SHIFT),
    '|': (_BASE['\\'], MOD_SHIFT), ':': (_BASE[';'], MOD_SHIFT),
    '"': (_BASE["'"], MOD_SHIFT), '<': (_BASE[','], MOD_SHIFT),
    '>': (_BASE['.'], MOD_SHIFT), '?': (_BASE['/'], MOD_SHIFT),
    '~': (_BASE['`'], MOD_SHIFT),
}

_COMBO_MOD = {
    'CTRL':    MOD_CTRL,
    'ALT':     MOD_ALT,
    'SHIFT':   MOD_SHIFT,
    'GUI':     MOD_GUI,
    'WINDOWS': MOD_GUI,
}


class DuckyModule:

    DEFAULT_DELAY = 0.01
    RELEASE_DELAY = 0.005

    def __init__(self, sentinel, hid_path: str = "/dev/hidg0"):
        self.sentinel = sentinel
        self.hid_path = hid_path
        self._fd = None

    def __enter__(self):
        self._fd = open(self.hid_path, 'rb+')
        return self

    def __exit__(self, *_):
        if self._fd:
            self._fd.close()
            self._fd = None

    def _write_report(self, modifier: int, key_code: int):
        reporte = bytearray(8)
        reporte[0] = modifier
        reporte[2] = key_code
        if self._fd:
            self._fd.write(reporte)
            self._fd.flush()
            time.sleep(self.RELEASE_DELAY)
            self._fd.write(bytearray(8))   # soltar tecla
            self._fd.flush()
        else:
            # Fallback: abrir/cerrar si no se usa como context manager
            with open(self.hid_path, 'rb+') as fd:
                fd.write(reporte)
                time.sleep(self.RELEASE_DELAY)
                fd.write(bytearray(8))

    def presionar(self, key_code: int, modifier: int = MOD_NONE):
        try:
            self._write_report(modifier, key_code)
        except OSError as e:
            logger.error("[HID] Error de escritura: %s", e)

    def escribir_texto(self, texto: str, delay: float = None):
        delay = delay if delay is not None else self.DEFAULT_DELAY
        for char in texto:
            if char in _SHIFT_MAP:
                code, mod = _SHIFT_MAP[char]
                self.presionar(code, mod)
            elif char.lower() in _BASE:
                self.presionar(_BASE[char.lower()])
            elif char == ' ':
                self.presionar(_BASE['SPACE'])
            else:
                logger.warning("[HID] Carácter no soportado: %r", char)
            time.sleep(delay)

    def combo(self, modifier: int, key: str):
        key_code = _BASE.get(key.lower()) or _BASE.get(key.upper())
        if key_code is None:
            logger.warning("[HID] Tecla de combo no reconocida: %r", key)
            return
        self.presionar(key_code, modifier)

    def ejecutar_script(self, ruta_script: str):
        try:
            with open(ruta_script, "r", encoding="utf-8") as f:
                lineas = f.readlines()
        except OSError as e:
            logger.error("[Script] No se pudo abrir %s: %s", ruta_script, e)
            return

        logger.info("[%s] Ejecutando Ducky Script: %s",
                    self.sentinel.nombre, ruta_script)

        for num, linea in enumerate(lineas, 1):
            linea = linea.rstrip("\n")
            if not linea or linea.startswith("REM"):   # comentarios
                continue

            partes = linea.strip().split(" ", 1)
            cmd = partes[0].upper()
            arg = partes[1] if len(partes) > 1 else ""

            try:
                if cmd == "STRING":
                    self.escribir_texto(arg)

                elif cmd == "DELAY":
                    time.sleep(int(arg) / 1000)

                elif cmd in _BASE:
                    self.presionar(_BASE[cmd])

                elif cmd in _COMBO_MOD:
                    mod = _COMBO_MOD[cmd]
                    if arg:
                        self.combo(mod, arg)
                    else:
                        self.presionar(0x00, mod)

                elif cmd == "DEFAULTDELAY" or cmd == "DEFAULT_DELAY":
                    self.DEFAULT_DELAY = int(arg) / 1000

                else:
                    logger.warning(
                        "[Script] Línea %d: comando desconocido %r", num, cmd)

            except (ValueError, IndexError) as e:
                logger.error("[Script] Línea %d error de parseo: %s", num, e)

        logger.info("[Script] Finalizado: %s", ruta_script)
