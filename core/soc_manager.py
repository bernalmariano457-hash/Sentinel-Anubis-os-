from __future__ import annotations

from pathlib import Path
from typing import Any

from core.async_runtime import AsyncRuntime
from core.tactical_soc import FeedSimulado, IngestaSuricata, ReglaRespuesta, ResponsePlaybook, TacticalSOC


class SOCManager:
    NOMBRE_TAREA = "tactical_soc"
    RUTA_EVE_JSON_DEFAULT = Path("/var/log/suricata/eve.json")

    def __init__(self, sentinel: Any, runtime: AsyncRuntime) -> None:
        self._sentinel = sentinel
        self._runtime = runtime

    @property
    def activo(self) -> bool:
        return self._runtime.tarea_activa(self.NOMBRE_TAREA)

    def iniciar(self, ruta_eve_json: str | None = None, dry_run: bool = True, simular: bool = False) -> None:
        c = self._sentinel.console
        if self.activo:
            c.print("[orange3][!] El SOC táctico ya está en ejecución.[/orange3]")
            return

        if not self._runtime.activo:
            self._runtime.iniciar()

        if simular:
            eventos_falsos = [
                {"event_type": "alert", "src_ip": "192.168.1.100", "alert": {
                    "severity": 1, "signature": "ET SCAN Potential SSH Scan"}},
                {"event_type": "alert", "src_ip": "10.0.0.50", "alert": {
                    "severity": 1, "signature": "ET MALWARE Possible Cobalt Strike"}}
            ]
            ingesta = FeedSimulado(eventos_falsos, intervalo=4.0)
            c.print(
                "[cyan][*] Usando FeedSimulado (inyectando ataques de prueba)...[/cyan]")
        else:
            ingesta = IngestaSuricata(
                Path(ruta_eve_json) if ruta_eve_json else self.RUTA_EVE_JSON_DEFAULT)
            c.print(
                f"[cyan][*] Leyendo logs de Suricata en: {ruta_eve_json or self.RUTA_EVE_JSON_DEFAULT}[/cyan]")

        def _alerta_visual(evento: dict[str, Any]) -> None:
            alerta = evento.get("alert", {})
            ip = evento.get("src_ip", "Desconocida")
            firma = alerta.get("signature", "Ataque detectado")

            self._sentinel.console.print(
                f"\n[bold red]⚠️ [SOC] ALERTA CRÍTICA:[/bold red] "
                f"[yellow]{firma}[/yellow] desde [bold white]{ip}[/bold white]"
            )

        regla = ReglaRespuesta(
            severidad_minima=1,
            cooldown_seg=30.0,
            ips_protegidas=frozenset({"127.0.0.1"}),
            dry_run=dry_run,
        )

        workspace = getattr(self._sentinel, "workspace", Path.cwd())
        operator_id = getattr(self._sentinel, "operator_id", "op-mariano")

        async def _fabrica_tarea() -> None:
            assert self._runtime.loop is not None
            playbook = ResponsePlaybook(
                loop=self._runtime.loop,
                workspace=workspace,
                operator_id=operator_id,
            )
            soc = TacticalSOC(ingesta, playbook, regla,
                              on_alerta=_alerta_visual)
            await soc.ejecutar()

        self._runtime.lanzar_tarea(self.NOMBRE_TAREA, _fabrica_tarea)
        modo = "DRY-RUN (simulando bloqueo)" if dry_run else "AUTÓNOMO (bloqueo iptables real)"
        c.print(
            f"[sea_green3][+] SOC táctico activo[/sea_green3] — modo: [bold]{modo}[/bold]")
        self._sentinel.log.info(
            f"SOC táctico iniciado (modo={modo}).", "SOCManager")

    def detener(self) -> None:
        c = self._sentinel.console
        if not self.activo:
            c.print("[orange3][!] El SOC táctico no está en ejecución.[/orange3]")
            return
        self._runtime.cancelar_tarea(self.NOMBRE_TAREA)
        c.print("[grey58][+] SOC táctico detenido.[/grey58]")
        self._sentinel.log.info("SOC táctico detenido.", "SOCManager")

    def estado(self) -> None:
        c = self._sentinel.console
        if not self.activo:
            c.print(
                "[dim][soc] Inactivo. Usa [bold white]soc start[/bold white] para iniciarlo.[/dim]")
            return
        c.print("[sea_green3][soc] Activo[/sea_green3] — vigilando alertas de red.")
