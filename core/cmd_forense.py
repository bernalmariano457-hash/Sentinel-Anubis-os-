from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich import box
from rich.markup import escape as _esc
from rich.table import Table

if TYPE_CHECKING:
    from Main import ApexSentinel

_recovery_results: dict[str, list] = {}


class ForenseCommands:

    s: "ApexSentinel"

    def recover(self, args: list[str]) -> None:
        if getattr(self.s, "recovery", None) is None:
            self.s.console.print(
                "[red][!] Módulo 'recovery' no disponible en este entorno.[/red]"
            )
            return

        if args and args[0].lower() == "ver":
            job_id = args[1].upper() if len(args) >= 2 else ""
            if not job_id:
                self.s.console.print(
                    "[yellow][!] Uso: recover ver <job_id>[/yellow]"
                )
                return
            self._recovery_mostrar_por_job(job_id)
            return

        ruta_str = args[0] if args else ""
        if not ruta_str:
            try:
                ruta_str = self.s.console.input(
                    "\n[bold cyan]  [?] Ruta de imagen (.dd/.img) o "
                    "dispositivo (/dev/sdX, /dev/mmcblkX)[/bold cyan]: "
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return

        if not ruta_str:
            self.s.console.print(
                "[yellow][!] Operación cancelada, no se indicó ruta.[/yellow]"
            )
            return

        if ruta_str.startswith("/dev/"):
            try:
                confirmacion = self.s.console.input(
                    f"\n[bold red]  [!] Vas a leer directamente el dispositivo "
                    f"de bloques {_esc(ruta_str)}. Esto puede tardar varios "
                    f"minutos en medios físicos grandes. "
                    f"Escribe CONFIRMAR para continuar[/bold red]: "
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return
            if confirmacion != "CONFIRMAR":
                self.s.console.print(
                    "[yellow][!] Operación cancelada por el operador.[/yellow]"
                )
                return

        self._recovery_encolar(Path(ruta_str))

    def _recovery_encolar(self, ruta: Path) -> None:
        s = self.s
        cola = getattr(s, "cola", None)

        if cola is None:
            s.console.print(
                f"[dim]Iniciando file carving sobre "
                f"{_esc(str(ruta))} (modo síncrono)...[/dim]"
            )
            try:
                resultados = s.recovery.execute(ruta)
            except Exception as error:
                s.console.print(
                    f"[red][!] Fallo durante el carving: {error}[/red]"
                )
                s.log.error(str(error), "Recovery")
                return
            self._recovery_registrar_evidencia(s, ruta, resultados)
            self._recovery_mostrar_tabla(resultados)
            return

        results_holder: list = []

        def _job_carving() -> str:
            resultados = s.recovery.execute(ruta)
            results_holder.append(resultados)
            self._recovery_registrar_evidencia(s, ruta, resultados)

            if not resultados:
                return "Sin archivos recuperados."

            total = len(resultados)
            completos = sum(1 for r in resultados if not r.truncated)
            lineas = [
                f"{total} archivo(s) recuperado(s) "
                f"({completos} completos, {total - completos} truncados)"
            ]
            for r in resultados[:5]:
                estado = "completo" if not r.truncated else "truncado"
                lineas.append(
                    f"  {r.signature_name:<8} "
                    f"offset={r.source_offset:<10} "
                    f"{r.size_bytes:>10,} B  {estado}"
                )
            if total > 5:
                lineas.append(f"  ... y {total - 5} más")
            return "\n".join(lineas)

        tarea = cola.agregar(
            f"file-carving: {ruta.name}",
            _job_carving,
            prioridad=2,
        )
        _recovery_results[tarea.id] = results_holder

        s.console.print(
            f"\n[dim]Job [bold cyan]#{tarea.id}[/bold cyan] encolado. "
            f"Progreso: [bold white]jobs[/bold white]  ·  "
            f"Tabla al finalizar: "
            f"[bold white]recover ver {tarea.id}[/bold white][/dim]\n"
        )

    @staticmethod
    def _recovery_registrar_evidencia(s: Any, ruta: Path, resultados: list[Any]) -> None:
        gp = getattr(s, "gp", None)
        if gp is None or getattr(gp, "proyecto_activo", None) is None:
            return
        total = len(resultados)
        completos = sum(1 for r in resultados if not r.truncated)
        gp.registrar_evidencia(
            "media_recovery",
            f"File carving sobre {ruta}: {total} archivos ({completos} completos)",
            datos={
                "fuente": str(ruta),
                "total": total,
                "completos": completos,
                "archivos": [str(r.output_path) for r in resultados],
            },
        )

    def _recovery_mostrar_por_job(self, job_id: str) -> None:
        holder = _recovery_results.get(job_id)
        if holder is None:
            self.s.console.print(
                f"[yellow][!] No hay resultados registrados para job #{job_id}. "
                f"Verifica el ID con [bold white]jobs[/bold white].[/yellow]"
            )
            return
        if not holder:
            self.s.console.print(
                f"[yellow][~] Job #{job_id} aún en ejecución, "
                f"espera a que finalice.[/yellow]"
            )
            return
        self._recovery_mostrar_tabla(holder[0])

    def _recovery_mostrar_tabla(self, resultados: list[Any]) -> None:
        if not resultados:
            self.s.console.print(
                "[yellow][!] No se recuperaron archivos.[/yellow]"
            )
            return

        tabla = Table(
            title=f"Archivos recuperados: {len(resultados)}",
            box=box.ROUNDED,
            border_style="green",
            header_style="bold green",
        )
        tabla.add_column("Firma",   style="cyan",      no_wrap=True)
        tabla.add_column("Offset",  style="dim",       justify="right")
        tabla.add_column("Tamaño",  style="white",     justify="right")
        tabla.add_column("Estado",  justify="center")
        tabla.add_column("Archivo", style="dim green", overflow="fold")

        completos = 0
        for resultado in resultados:
            if resultado.truncated:
                estado_fmt = "[yellow]truncado[/yellow]"
            else:
                estado_fmt = "[bold green]completo[/bold green]"
                completos += 1
            tabla.add_row(
                resultado.signature_name,
                str(resultado.source_offset),
                f"{resultado.size_bytes:,} B",
                estado_fmt,
                str(resultado.output_path),
            )

        self.s.console.print(tabla)
        self.s.console.print(
            f"[dim]{completos}/{len(resultados)} con longitud exacta confirmada "
            f"· resto truncado por límite de seguridad o corte de fuente.[/dim]\n"
        )
        self.s.log.info(
            f"Recovery: {len(resultados)} archivos ({completos} completos).",
            "Recovery",
        )
