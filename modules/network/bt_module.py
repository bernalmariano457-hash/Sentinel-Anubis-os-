import asyncio
from bleak import BleakScanner


class BluetoothModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel

    def iniciar_jumper(self):
        print("[*] Buscando dispositivos Bluetooth cercanos...")
        # Usamos asyncio para que no bloquee el Sentinel
        try:
            asyncio.run(self.escanear())
        except Exception as e:
            print(f"[-] Error en Bluetooth: {e}")

    async def escanear(self):
        devices = await BleakScanner.discover()
        for d in devices:
            print(f"[+] Encontrado: {d.name} - {d.address}")

    def puente(self, origen, destino):
        try:
            while True:
                data = origen.recv(1024)
                if len(data) == 0:
                    break
                # Aquí puedes ver los datos que pasan por el Jumper
                print(f"-> Transferido: {len(data)} bytes")
                destino.send(data)
        except:
            pass
        finally:
            origen.close()
            destino.close()
