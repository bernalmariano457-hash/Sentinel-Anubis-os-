from __future__ import annotations

import os
import subprocess

from rich.panel import Panel

from core._base import _DomainBase


class MobileCommands(_DomainBase):

    # ── Triage básico ─────────────────────────────────────────────────

    def mobile(self) -> None:
        s = self.s
        if not self._modulo_ok("mobile"):
            return
        self.console.print(
            "\n[1] Android Triage  [2] iOS Info  [3] Screenshot")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            s.mobile.triage_android()
        elif opt == "2":
            s.mobile.triage_ios()
        elif opt == "3":
            path = s.mobile.preparar_directorio("Android_Screen")
            self.console.print("[*] Tomando captura...")
            try:
                s._run(["adb", "shell", "screencap",
                       "-p", "/sdcard/s.png"], timeout=15)
                s._run(["adb", "pull", "/sdcard/s.png",
                       f"{path}/s.png"], timeout=15)
                self.console.print(
                    f"[green][+] Captura guardada en {path}/s.png[/green]")
                s.log.success(
                    f"Screenshot guardado en {path}/s.png", "MobileSentinel")
            except subprocess.TimeoutExpired:
                self.console.print(
                    "[red][!] ADB timeout. Verifica conexión.[/red]")
                s.log.error("ADB timeout screenshot", "MobileSentinel")
            except subprocess.CalledProcessError as e:
                self.console.print(
                    f"[red][!] Error ADB ({e.returncode}): {e}[/red]")
                s.log.error(f"Screenshot ADB: {e}", "MobileSentinel")
            except Exception as e:
                self.console.print(f"[red][!] Error inesperado ADB: {e}[/red]")

    # ── Extracción profunda ───────────────────────────────────────────

    def mobile_deep(self) -> None:
        s = self.s
        path = "./data/evidence/mobile/Deep_Extraction/"
        os.makedirs(path, exist_ok=True)

        self.console.print(
            "\n[1] Extraer WhatsApp Full  "
            "[2] Extraer Chrome History  "
            "[3] Descifrar crypt (WADecryptor)"
        )
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()

        if opt in ("1", "2"):
            if s._db_extractor_cls is None:
                self.console.print(
                    "[red][!] DatabaseExtractor no disponible.[/red]")
                return
            extractor = s._db_extractor_cls()
            s.animar_barra("EXTRAYENDO DB Y LLAVE..." if opt == "1"
                           else "EXTRAYENDO HISTORIAL CHROME...")
            if opt == "1":
                extractor.extraer_whatsapp(path)
                extractor.extraer_whatsapp_key(path)
                s.log.audit("Extracción WhatsApp completada", "MobileDeep")
            else:
                s.log.audit("Extracción Chrome completada", "MobileDeep")

        elif opt == "3":
            if s._wa_decryptor_cls is None:
                self.console.print("[red][!] WADecryptor no disponible.[/red]")
                return
            crypt_file = self.console.input(
                "[bold cyan][?] Ruta archivo .crypt12/.crypt14/.crypt15: [/bold cyan]"
            ).strip().strip("'\"")
            key_file = self.console.input(
                "[bold cyan][?] Ruta archivo key: [/bold cyan]"
            ).strip().strip("'\"")
            if not crypt_file or not key_file:
                self.console.print("[red][!] Rutas inválidas.[/red]")
                return
            output_file = os.path.join(path, "whatsapp_decrypted.db")
            try:
                decryptor = s._wa_decryptor_cls(verbose=False)
                if decryptor.descifrar(crypt_file, key_file, output_file):
                    s.log.audit(
                        f"WA descifrado OK → {output_file}", "MobileDeep")
                    self.console.print(
                        f"[green][+] DB lista en: {output_file}[/green]\n"
                        "[dim]Usa el comando [bold white]view[/bold white] para leerla.[/dim]")
                else:
                    s.log.error(
                        "WADecryptor: descifrado fallido", "MobileDeep")
            except Exception as e:
                self.console.print(f"[red][!] Error en descifrado: {e}[/red]")
                s.log.error(f"WADecryptor: {e}", "MobileDeep")

    # ── Lector forense ────────────────────────────────────────────────

    def view(self) -> None:
        s = self.s
        if not self._modulo_ok("reader"):
            return
        ruta_base = "./data/evidence/mobile/Deep_Extraction/"
        self.console.print(
            "\n[bold cyan]VIEW — Lector Forense[/bold cyan]\n"
            "[1] WhatsApp (Android/iOS auto)\n[2] Chrome History\n[3] Firefox places.sqlite\n"
            "[4] Safari History.db\n[5] Registro de llamadas WA\n"
            "[6] Buscar mensajes eliminados\n[7] Top contactos + timeline de actividad\n"
            "[8] Buscar palabras clave en mensajes\n[9] Exportar reporte HTML completo"
        )
        opcion = self.console.input("[bold cyan] > [/bold cyan]").strip()

        def _db(default_name: str) -> str:
            return (
                self.console.input(
                    f"[dim][Enter] = {ruta_base}{default_name} > [/dim]").strip()
                or os.path.join(ruta_base, default_name)
            )

        if opcion == "1":
            s.reader.leer_whatsapp_mensajes(_db("whatsapp_decrypted.db"))
        elif opcion == "2":
            s.reader.leer_historial_chrome(_db("chrome_history.db"))
        elif opcion == "3":
            s.reader.leer_historial_firefox(_db("places.sqlite"))
        elif opcion == "4":
            s.reader.leer_historial_safari(_db("History.db"))
        elif opcion == "5":
            db = _db("whatsapp_decrypted.db")
            llamadas = s.reader.leer_llamadas_android(db)
            s.reader.mostrar_llamadas(llamadas)
        elif opcion == "6":
            db = _db("whatsapp_decrypted.db")
            eliminados = s.reader.leer_mensajes_eliminados(db)
            if eliminados:
                self.console.print(
                    f"[yellow][!] {len(eliminados)} registros potencialmente eliminados:[/yellow]")
                for e in eliminados:
                    self.console.print(
                        f"  [{e['fecha_display']}] [bold]{e['contacto']}[/bold]: "
                        f"{e['texto_recuperado']}")
            else:
                self.console.print(
                    "[dim]Sin registros eliminados detectados.[/dim]")
        elif opcion == "7":
            db = _db("whatsapp_decrypted.db")
            mensajes, _ = s.reader.leer_whatsapp_mensajes(db)
            if mensajes:
                stats = s.reader.analizar_frecuencia_contactos(mensajes)
                s.reader.mostrar_frecuencia_contactos(stats)
                tl = s.reader.analizar_timeline_horas(mensajes)
                s.reader.mostrar_timeline_horas(tl)
        elif opcion == "8":
            db = _db("whatsapp_decrypted.db")
            kw_raw = self.console.input(
                "[bold cyan][?] Palabras clave (separadas por espacio): [/bold cyan]"
            ).strip()
            if not kw_raw:
                return
            keywords = kw_raw.split()
            mensajes, _ = s.reader.leer_whatsapp_mensajes(db)
            encontrados = s.reader.buscar_palabras_clave(mensajes, keywords)
            self.console.print(
                f"[yellow]{len(encontrados)} mensajes con: {keywords}[/yellow]")
            for m in encontrados:
                self.console.print(
                    f"  [{m.fecha_iso}] [bold]{m.contacto}[/bold]: {m.texto}")
        elif opcion == "9":
            db = _db("whatsapp_decrypted.db")
            out_html = os.path.join(ruta_base, "reporte_forense.html")
            mensajes,  resumen = s.reader.leer_whatsapp_mensajes(db)
            llamadas = s.reader.leer_llamadas_android(db)
            eliminados = s.reader.leer_mensajes_eliminados(db)
            frecuencia = s.reader.analizar_frecuencia_contactos(
                mensajes) if mensajes else None
            timeline = s.reader.analizar_timeline_horas(
                mensajes) if mensajes else None
            s.reader.exportar_html(
                out_html, mensajes=mensajes or None, resumen=resumen,
                llamadas=llamadas or None, eliminados=eliminados or None,
                frecuencia=frecuencia, timeline=timeline,
            )
            s.log.audit(
                f"Reporte HTML generado → {out_html}", "ForensicReader")
