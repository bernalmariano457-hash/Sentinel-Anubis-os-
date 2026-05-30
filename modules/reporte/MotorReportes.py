from __future__ import annotations

import os
import json
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich import box

SEVERIDAD_ORDEN = {"CRITICO": 0, "ALTO": 1, "MEDIO": 2, "BAJO": 3, "INFO": 4}
SEVERIDAD_EMOJI = {
    "CRITICO": "🔴", "ALTO": "🟠",
    "MEDIO":   "🟡", "BAJO": "🔵", "INFO": "⚪"
}


class MotorReportes:

    def __init__(self, gestor_proyectos):
        self.gp = gestor_proyectos
        from rich.console import Console
        self.console = Console()

    # ------------------------------------------------------------------
    # API PÚBLICA
    # ------------------------------------------------------------------

    def generar_reporte_completo(self):
        p = self.gp.proyecto_activo
        if not p:
            self.console.print("[yellow][!] No hay proyecto activo.[/yellow]")
            return

        with Progress(
            SpinnerColumn(style="green"),
            TextColumn("[cyan]{task.description}[/cyan]"),
            BarColumn(bar_width=20, style="green"),
            TextColumn("[green]{task.percentage:>3.0f}%[/green]"),
            console=self.console,
        ) as progress:
            tarea = progress.add_task("Generando reporte...", total=5)

            progress.update(tarea, description="Construyendo encabezado...")
            contenido = self._seccion_encabezado(p)
            progress.advance(tarea)

            progress.update(tarea, description="Resumen ejecutivo...")
            contenido += self._seccion_resumen_ejecutivo(p)
            progress.advance(tarea)

            progress.update(tarea, description="Hallazgos de seguridad...")
            contenido += self._seccion_hallazgos(p)
            progress.advance(tarea)

            progress.update(tarea, description="Timeline de evidencias...")
            contenido += self._seccion_evidencias(p)
            progress.advance(tarea)

            progress.update(tarea, description="Conclusiones...")
            contenido += self._seccion_conclusiones(p)
            progress.advance(tarea)

        # Guardar en el workspace del proyecto
        nombre_archivo = f"reporte_{p.id}_{datetime.now().strftime('%H%M%S')}.md"
        ruta_reporte = os.path.join(p.ruta, "reports", nombre_archivo)

        try:
            with open(ruta_reporte, "w", encoding="utf-8") as f:
                f.write(contenido)

            self.console.print(Panel(
                f"[green]Reporte generado exitosamente[/green]\n\n"
                f"[cyan]Archivo:[/cyan]    {nombre_archivo}\n"
                f"[cyan]Ruta:[/cyan]       {ruta_reporte}\n"
                f"[cyan]Hallazgos:[/cyan]  {len(p.hallazgos)}\n"
                f"[cyan]Evidencias:[/cyan] {len(p.evidencias)}\n"
                f"[cyan]Tamaño:[/cyan]     {len(contenido):,} caracteres",
                title="[bold green]REPORTE GENERADO[/bold green]",
                border_style="green"
            ))
            return ruta_reporte

        except OSError as e:
            self.console.print(f"[red][!] Error al guardar reporte: {e}[/red]")
            return None

    def generar_resumen_ejecutivo(self):
        p = self.gp.proyecto_activo
        if not p:
            self.console.print("[yellow][!] No hay proyecto activo.[/yellow]")
            return

        criticos = sum(1 for h in p.hallazgos if h["severidad"] == "CRITICO")
        altos = sum(1 for h in p.hallazgos if h["severidad"] == "ALTO")
        medios = sum(1 for h in p.hallazgos if h["severidad"] == "MEDIO")

        resumen = (
            f"RESUMEN EJECUTIVO — {p.nombre}\n"
            f"{'='*50}\n"
            f"Fecha:      {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Objetivo:   {p.objetivo}\n"
            f"Scope:      {p.scope}\n"
            f"Tipo:       {p.tipo}\n\n"
            f"HALLAZGOS\n"
            f"{'-'*30}\n"
            f"Críticos:   {criticos}\n"
            f"Altos:      {altos}\n"
            f"Medios:     {medios}\n"
            f"Total:      {len(p.hallazgos)}\n\n"
            f"NIVEL DE RIESGO GENERAL: {self._nivel_riesgo(criticos, altos, medios)}\n\n"
            f"EVIDENCIAS RECOLECTADAS: {len(p.evidencias)}\n"
        )

        nombre = f"resumen_ejecutivo_{p.id}.txt"
        ruta = os.path.join(p.ruta, "reports", nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(resumen)

        self.console.print(resumen)
        self.console.print(f"[dim]Guardado en: {ruta}[/dim]")

    def generar_timeline(self):
        p = self.gp.proyecto_activo
        if not p:
            self.console.print("[yellow][!] No hay proyecto activo.[/yellow]")
            return

        lineas = [
            f"# TIMELINE DE OPERACIÓN — {p.nombre}\n",
            f"Objetivo: {p.objetivo} | Scope: {p.scope}\n",
            f"{'─'*60}\n\n",
        ]

        todos = []
        for e in p.evidencias:
            todos.append(("evidencia", e["timestamp"], e))
        for h in p.hallazgos:
            todos.append(("hallazgo", h["timestamp"], h))

        todos.sort(key=lambda x: x[1])

        for tipo, ts, item in todos:
            hora = ts[11:19] if len(ts) > 10 else ts
            if tipo == "evidencia":
                lineas.append(
                    f"[{hora}] 📋 EVIDENCIA — {item['tipo']}: {item['descripcion']}\n"
                )
            else:
                emoji = SEVERIDAD_EMOJI.get(item["severidad"], "⚪")
                lineas.append(
                    f"[{hora}] {emoji} HALLAZGO {item['severidad']} — {item['titulo']}\n"
                )

        contenido = "".join(lineas)
        nombre = f"timeline_{p.id}.txt"
        ruta = os.path.join(p.ruta, "reports", nombre)

        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)

        self.console.print(
            Panel(contenido, title="TIMELINE", border_style="cyan")
        )
        self.console.print(f"[dim]Guardado en: {ruta}[/dim]")

    # ------------------------------------------------------------------
    # SECCIONES DEL REPORTE MARKDOWN
    # ------------------------------------------------------------------

    def _seccion_encabezado(self, p) -> str:
        return (
            f"# Reporte de Seguridad — {p.nombre}\n\n"
            f"| Campo        | Valor |\n"
            f"|--------------|-------|\n"
            f"| **Proyecto** | {p.nombre} |\n"
            f"| **ID**       | {p.id} |\n"
            f"| **Objetivo** | {p.objetivo} |\n"
            f"| **Scope**    | {p.scope} |\n"
            f"| **Tipo**     | {p.tipo} |\n"
            f"| **Fecha**    | {datetime.now().strftime('%Y-%m-%d %H:%M')} |\n"
            f"| **Estado**   | {p.estado} |\n\n"
            f"---\n\n"
        )

    def _seccion_resumen_ejecutivo(self, p) -> str:
        criticos = sum(1 for h in p.hallazgos if h["severidad"] == "CRITICO")
        altos = sum(1 for h in p.hallazgos if h["severidad"] == "ALTO")
        medios = sum(1 for h in p.hallazgos if h["severidad"] == "MEDIO")
        bajos = sum(1 for h in p.hallazgos if h["severidad"] == "BAJO")
        riesgo = self._nivel_riesgo(criticos, altos, medios)

        return (
            f"## Resumen Ejecutivo\n\n"
            f"Se realizó una evaluación de seguridad sobre el objetivo **{p.objetivo}** "
            f"dentro del scope definido **{p.scope}**.\n\n"
            f"### Métricas\n\n"
            f"| Severidad  | Cantidad |\n"
            f"|------------|----------|\n"
            f"| 🔴 Crítico | {criticos} |\n"
            f"| 🟠 Alto    | {altos} |\n"
            f"| 🟡 Medio   | {medios} |\n"
            f"| 🔵 Bajo    | {bajos} |\n"
            f"| **Total**  | **{len(p.hallazgos)}** |\n\n"
            f"**Nivel de riesgo general: {riesgo}**\n\n"
            f"Se recolectaron **{len(p.evidencias)}** evidencias durante la operación.\n\n"
            f"---\n\n"
        )

    def _seccion_hallazgos(self, p) -> str:
        if not p.hallazgos:
            return "## Hallazgos\n\nNo se registraron hallazgos.\n\n---\n\n"

        ordenados = sorted(
            p.hallazgos,
            key=lambda h: SEVERIDAD_ORDEN.get(h["severidad"], 99)
        )

        seccion = "## Hallazgos de Seguridad\n\n"
        for i, h in enumerate(ordenados, 1):
            emoji = SEVERIDAD_EMOJI.get(h["severidad"], "⚪")
            seccion += (
                f"### {i}. {emoji} [{h['severidad']}] {h['titulo']}\n\n"
                f"**Fecha:** {h['timestamp'][:19]}\n\n"
                f"**Descripción:**\n{h['descripcion']}\n\n"
            )
            if h.get("recomendacion"):
                seccion += f"**Recomendación:**\n{h['recomendacion']}\n\n"
            seccion += "---\n\n"

        return seccion

    def _seccion_evidencias(self, p) -> str:
        if not p.evidencias:
            return "## Evidencias\n\nNo se registraron evidencias.\n\n---\n\n"

        seccion = "## Evidencias Recolectadas\n\n"
        seccion += "| # | Tipo | Descripción | Timestamp |\n"
        seccion += "|---|------|-------------|----------|\n"

        for i, e in enumerate(p.evidencias, 1):
            seccion += (
                f"| {i} | `{e['tipo']}` | {e['descripcion']} "
                f"| {e['timestamp'][:19]} |\n"
            )

        seccion += "\n---\n\n"

        # Detalle de datos por evidencia
        for i, e in enumerate(p.evidencias, 1):
            if e.get("datos"):
                seccion += f"### Evidencia {i} — {e['tipo']}\n\n"
                seccion += f"```json\n{json.dumps(e['datos'], indent=2, ensure_ascii=False)}\n```\n\n"

        return seccion

    def _seccion_conclusiones(self, p) -> str:
        criticos = sum(1 for h in p.hallazgos if h["severidad"] == "CRITICO")
        altos = sum(1 for h in p.hallazgos if h["severidad"] == "ALTO")
        riesgo = self._nivel_riesgo(criticos, altos, 0)

        return (
            f"## Conclusiones\n\n"
            f"La evaluación del objetivo **{p.objetivo}** concluye con un nivel de "
            f"riesgo **{riesgo}**.\n\n"
            f"Se identificaron **{len(p.hallazgos)}** hallazgos en total, "
            f"de los cuales **{criticos}** son críticos y **{altos}** son de severidad alta. "
            f"Se recomienda atender los hallazgos críticos y altos de forma inmediata.\n\n"
            f"## Notas del Operador\n\n"
            f"{p.notas if p.notas else '_Sin notas adicionales._'}\n\n"
            f"---\n\n"
            f"*Reporte generado automáticamente por AnubisOS Apex Sentinel v2.1*\n"
            f"*Fecha de generación: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"
        )

    def _nivel_riesgo(self, criticos: int, altos: int, medios: int) -> str:
        if criticos > 0:
            return "🔴 CRÍTICO"
        if altos > 0:
            return "🟠 ALTO"
        if medios > 0:
            return "🟡 MEDIO"
        return "🔵 BAJO"


# --- Prueba directa ---
if __name__ == "__main__":
    from core.GestorProyectos import GestorProyectos

    gp = GestorProyectos()
    gp.crear_proyecto()

    gp.registrar_evidencia("portscan", "Puerto 22 abierto",
                           {"puerto": 22, "servicio": "SSH", "version": "OpenSSH 8.2"})
    gp.registrar_evidencia("portscan", "Puerto 80 abierto",
                           {"puerto": 80, "servicio": "HTTP", "server": "Apache 2.4.41"})
    gp.registrar_hallazgo("ALTO", "SSH expuesto sin restricción",
                          "El servicio SSH acepta conexiones desde cualquier IP.",
                          "Restringir acceso por IP en firewall.")
    gp.registrar_hallazgo("MEDIO", "Apache versión desactualizada",
                          "Apache 2.4.41 tiene CVEs conocidos.",
                          "Actualizar a la última versión estable.")

    motor = MotorReportes(gp)
    motor.generar_reporte_completo()
    motor.generar_resumen_ejecutivo()
    motor.generar_timeline()
