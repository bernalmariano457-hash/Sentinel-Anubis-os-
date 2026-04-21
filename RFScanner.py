import numpy as np

# ==========================================
# 🛡️ CAPA DE COMPATIBILIDAD (BYPASS)
# ==========================================
try:
    from rtlsdr import RtlSdr
    SDR_LIBRERIA_LISTA = True
except ImportError:
    SDR_LIBRERIA_LISTA = False
    # Clase ficticia para que el código no explote si falta la DLL o la librería

    class RtlSdr:
        def __init__(self): pass
        def read_samples(self, size): return np.zeros(size)
        def close(self): pass


class RFScanner:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.sdr = None
        if not SDR_LIBRERIA_LISTA:
            print(
                "\033[1;33m[!] RFScanner: Librerías SDR no detectadas. Modo SIMULACIÓN activo.\033[0m")

    def iniciar_sdr(self):
        """Intenta inicializar el hardware real."""
        if not SDR_LIBRERIA_LISTA:
            print("[SIMULACIÓN] Hardware SDR virtualizado para pruebas de software.")
            return True  # Retorna True para permitir que el flujo del programa siga

        try:
            self.sdr = RtlSdr()
            # Configuración estándar inicial
            self.sdr.sample_rate = 2.048e6  # 2MHz de ancho de banda
            self.sdr.gain = 'auto'
            return True
        except Exception:
            print(
                "\033[1;31m[!] Error: No se detectó hardware SDR físico conectado.\033[0m")
            return False

    def escanear_frecuencia(self, freq_mhz, duracion=5):
        """Escanea una frecuencia específica y busca picos de señal."""
        # Si no hay hardware y no se puede iniciar, trabajamos en modo simulación
        if not self.sdr and not self.iniciar_sdr():
            print("[!] Abortando escaneo: Hardware no disponible.")
            return

        print(f"[*] Sintonizando Anubis en {freq_mhz} MHz...")

        if not SDR_LIBRERIA_LISTA or self.sdr is None:
            # Lógica de Simulación: Genera un resultado aleatorio para probar el reporte
            potencia_simulada = np.random.random() * 0.02
            self._procesar_resultado(freq_mhz, potencia_simulada)
        else:
            # Lógica Real con hardware
            freq_hz = freq_mhz * 1e6
            self.sdr.center_freq = freq_hz
            muestras = self.sdr.read_samples(256 * 1024)
            potencia = np.mean(np.abs(muestras)**2)
            self._procesar_resultado(freq_mhz, potencia)

    def procesar_resultado(self, freq_mhz, potencia):
        """Maneja la salida de datos y el registro de eventos."""
        if potencia > 0.01:  # Umbral de detección
            print(
                f"\033[1;32m[+] SEÑAL DETECTADA en {freq_mhz} MHz (Potencia: {potencia:.4f})\033[0m")
            self.sentinel.reportes.registrar_evento(
                "RF", f"Actividad en {freq_mhz} MHz")
        else:
            print(f"[-] Frecuencia {freq_mhz} MHz en silencio.")

    def cerrar(self):
        if self.sdr and SDR_LIBRERIA_LISTA:
            self.sdr.close()
