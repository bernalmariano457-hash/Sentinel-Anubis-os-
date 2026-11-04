from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sentinel import SentinelError, __version__
from sentinel.integrity.baseline import Baseline
from sentinel.integrity.keys import (
    DEFAULT_SERVICE,
    KeyManager,
    OperatorIdentity,
    SentinelKeyError,
)
from sentinel.integrity.timestamp import SystemClock
from sentinel.packaging.sae import (
    SAEError,
    SAEVerificationReport,
    pack,
)
from sentinel.packaging.sae import (
    verify as verify_sae,
)
from sentinel.reporting.json_report import generate_report
from sentinel.reporting.pdf_report import generate_pdf_report
from sentinel.security import Lockdown, LockState, StateError, read_state
from sentinel.security.state import STATE_FILENAME

console = Console()
err_console = Console(stderr=True)


@click.group()
@click.version_option(version=__version__, prog_name="sentinel")
def main() -> None:
    pass


@main.command(name="verify")
@click.argument(
    "package",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--operator",
    "operator_paths",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Operator .pub file for signature verification (repeatable).",
)
@click.option("--no-custody", is_flag=True, help="Skip custody chain verification.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def cmd_verify(
    package: Path,
    operator_paths: tuple[Path, ...],
    no_custody: bool,
    as_json: bool,
) -> None:
    operators: dict[str, OperatorIdentity] = {}
    for op_path in operator_paths:
        try:
            ident = KeyManager.load_public(op_path)
        except (SentinelKeyError, OSError) as e:
            err_console.print(
                f"[red]error:[/red] cannot load operator {op_path}: {e}")
            sys.exit(2)
        operators[ident.operator_id] = ident

    try:
        report = verify_sae(
            package,
            operators=operators if operators else None,
            verify_custody_chain=not no_custody,
        )
    except SAEError as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)

    if as_json:
        click.echo(json.dumps(report_to_dict(report),
                   indent=2, ensure_ascii=False))
    else:
        print_report(report)

    sys.exit(0 if report.valid else 1)


def report_to_dict(report: SAEVerificationReport) -> dict[str, Any]:
    return {
        "valid": report.valid,
        "package_id": report.package_id,
        "signatures_verified": report.signatures_verified,
        "custody_chain_valid": report.custody_chain_valid,
        "artifacts_total": report.artifacts_total,
        "artifacts_valid": report.artifacts_valid,
        "issues": [
            {"code": i.code, "message": i.message, "location": i.location}
            for i in report.issues
        ],
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "valid": a.valid,
                "file_count": a.file_count,
                "signature_verified": a.signature_verified,
            }
            for a in report.artifacts
        ],
    }


def print_report(report: SAEVerificationReport) -> None:
    status_color = "green" if report.valid else "red"
    status_text = "VALID" if report.valid else "INVALID"
    console.print(
        Panel(
            f"[bold {status_color}]{status_text}[/bold {status_color}]\n"
            f"{report.summary()}",
            title=f".sae {report.package_id or '<unknown>'}",
        )
    )

    if report.artifacts:
        t = Table(title="Artifacts")
        t.add_column("artifact_id", style="cyan")
        t.add_column("files", justify="right")
        t.add_column("signature")
        t.add_column("status")
        for a in report.artifacts:
            t.add_row(
                a.artifact_id,
                str(a.file_count),
                "[green]ok[/green]" if a.signature_verified else "[dim]skipped[/dim]",
                "[green]ok[/green]" if a.valid else "[red]invalid[/red]",
            )
        console.print(t)

    if report.issues:
        t = Table(title="Issues")
        t.add_column("code", style="yellow")
        t.add_column("location", style="dim")
        t.add_column("message")
        for i in report.issues:
            t.add_row(i.code, i.location or "", i.message)
        console.print(t)


@main.command(name="keygen")
@click.option("--name", required=True, help="Human-readable display name.")
@click.option("--operator-id", default=None, help="Optional custom operator_id.")
@click.option("--service", default=None, help="Keyring service name.")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write operator.pub to this path.",
)
def cmd_keygen(
    name: str,
    operator_id: str | None,
    service: str | None,
    output: Path | None,
) -> None:
    try:
        km = KeyManager.generate(
            display_name=name,
            operator_id=operator_id,
            service=service or DEFAULT_SERVICE,
        )
    except (SentinelKeyError, ValueError) as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)

    console.print(
        Panel(
            f"operator_id: [cyan]{km.identity.operator_id}[/cyan]\n"
            f"fingerprint: [cyan]{km.identity.pubkey_fingerprint}[/cyan]",
            title="New operator created",
            border_style="green",
        )
    )

    if output is not None:
        km.save_public(output)
        console.print(f"public key written to [cyan]{output}[/cyan]")


@main.command(name="show-operator")
@click.argument(
    "operator_pub",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def cmd_show_operator(operator_pub: Path) -> None:
    try:
        ident = KeyManager.load_public(operator_pub)
    except (SentinelKeyError, OSError) as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)

    console.print(
        Panel(
            f"operator_id: [cyan]{ident.operator_id}[/cyan]\n"
            f"display_name: {ident.display_name}\n"
            f"fingerprint: [cyan]{ident.pubkey_fingerprint}[/cyan]\n"
            f"created_at: {ident.created_at}",
            title=str(operator_pub),
        )
    )


_WORKSPACE_OPTION = click.option(
    "--workspace",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Workspace directory.",
)

_STATE_STYLES = {
    LockState.NORMAL: "green",
    LockState.LOCKED: "red",
    LockState.UNLOCKED: "yellow",
}


@main.command("vault-setup")
@_WORKSPACE_OPTION
@click.option("--operator-id", required=True, help="Operator that owns the vault.")
@click.option("--passphrase", prompt=True, hide_input=True, confirmation_prompt=True)
def vault_setup(workspace: Path, operator_id: str, passphrase: str) -> None:
    try:
        km = KeyManager.load(operator_id, operator_id)
        Lockdown(workspace, km).setup(passphrase)
    except (SentinelError, ValueError) as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)
    console.print(f"[green]vault ready[/green] in {workspace}")


@main.command("lock")
@_WORKSPACE_OPTION
@click.option("--operator-id", required=True, help="Operator signing the lock.")
@click.option("--reason", default="manual", show_default=True)
@click.option("--passphrase", prompt=True, hide_input=True)
def lock(workspace: Path, operator_id: str, reason: str, passphrase: str) -> None:
    """Encrypt and remove evidence from the workspace."""
    try:
        km = KeyManager.load(operator_id, operator_id)
        record = Lockdown(workspace, km).lock(passphrase, reason=reason)
    except (SentinelError, ValueError) as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)
    console.print(
        f"[red]locked[/red] at {record.changed_at} ({record.reason})")


@main.command("unlock")
@_WORKSPACE_OPTION
@click.option("--operator-id", required=True, help="Operator that signed the lock.")
@click.option("--passphrase", prompt=True, hide_input=True)
def unlock(workspace: Path, operator_id: str, passphrase: str) -> None:
    try:
        km = KeyManager.load(operator_id, operator_id)
        record = Lockdown(workspace, km).unlock(passphrase)
    except (SentinelError, ValueError) as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)
    console.print(f"[yellow]unlocked[/yellow] at {record.changed_at}")


@main.command("status")
@_WORKSPACE_OPTION
def status(workspace: Path) -> None:
    if not (workspace / STATE_FILENAME).exists():
        console.print("no state file (normal)")
        return
    try:
        record = read_state(workspace)
    except StateError as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)
    style = _STATE_STYLES[record.state]
    console.print(f"state:    [{style}]{record.state.value}[/{style}]")
    console.print(f"changed:  {record.changed_at}")
    console.print(f"reason:   {record.reason}")
    console.print(f"operator: [cyan]{record.operator_id}[/cyan]")


@main.group(name="baseline")
def baseline_group() -> None:
    pass


@baseline_group.command("create")
@click.option("--workspace", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--operator-id", required=True, help="Operator signing the baseline.")
def baseline_create(workspace: Path, operator_id: str) -> None:

    try:
        km = KeyManager.load(operator_id, operator_id)
        ts = SystemClock().now()
        bl = Baseline.create(km, workspace, ts)
        out_path = workspace / "baseline.json"
        bl.save(out_path)
    except Exception as e:
        err_console.print(f"[red]error:[/red] {e}")
        sys.exit(2)

    console.print("[green]Baseline created successfully[/green]")
    console.print(f"Signed by: {operator_id}")
    console.print(f"Files tracked: {len(bl.files)}")
    console.print(f"Saved to: {out_path}")


@main.command("report")
@click.option("--workspace", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--operator-id", required=True, help="Operator who signed the log.")
def cmd_report(workspace: Path, operator_id: str) -> None:
    try:
        # 1. Generar JSON
        json_path = generate_report(workspace, operator_id)
        console.print(f"[green]JSON Report generated:[/green] {json_path}")

        # 2. Generar PDF
        pdf_path = workspace / f"{json_path.stem}.pdf"
        generate_pdf_report(json_path, pdf_path)
        console.print(f"[green]PDF Report generated:[/green] {pdf_path}")

    except Exception as e:
        err_console.print(f"[red]error generating report:[/red] {e}")
        sys.exit(2)


@main.command("pack")
@click.option("--workspace", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--operator-id", required=True, help="Operator signing the package.")
@click.option("--operation-id", required=True, help="Operation this package belongs to.")
@click.option("--output", type=click.Path(file_okay=True, path_type=Path), required=True, help="Output .sae file.")
def cmd_pack(
    workspace: Path, operator_id: str, operation_id: str, output: Path
) -> None:
    try:
        km = KeyManager.load(operator_id, operator_id)

        # Buscar artefactos (asumiendo que están en data/evidence)
        evidence_dir = workspace / "data" / "evidence"
        artifact_dirs = [d for d in evidence_dir.iterdir(
        ) if d.is_dir()] if evidence_dir.exists() else []

        if not artifact_dirs:
            err_console.print(
                "[red]No artifact directories found in data/evidence — "
                "cannot pack without valid artifacts.[/red]")
            sys.exit(2)

        custody_path = workspace / "custody.log"
        if not custody_path.exists():
            console.print("[red]No custody.log found in workspace.[/red]")
            sys.exit(2)

        console.print(
            f"[cyan]Packing {len(artifact_dirs)} artifacts and custody log...[/cyan]")

        manifest = pack(
            output_path=output,
            operator=km,
            operation_id=operation_id,
            artifact_dirs=artifact_dirs,
            custody_log_path=custody_path
        )

        console.print(f"[green]Package created:[/green] {output}")
        console.print(f"Package ID: {manifest['package_id']}")

    except Exception as e:
        err_console.print(f"[red]error packing evidence:[/red] {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
