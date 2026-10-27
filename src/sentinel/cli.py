from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sentinel import __version__
from sentinel.integrity.keys import (
    DEFAULT_SERVICE,
    KeyManager,
    OperatorIdentity,
    SentinelKeyError,
)
from sentinel.packaging.sae import (
    SAEError,
    SAEVerificationReport,
    verify as verify_sae,
)

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


if __name__ == "__main__":
    main()
