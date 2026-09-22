from __future__ import annotations
from modules.integrity.hash_chain import ChainIntegrityError, HashChainLogger, VerificationResult

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))


EXIT_OK = 0
EXIT_OPERATIONAL_ERROR = 1
EXIT_INTEGRITY_VIOLATION = 2


class VerifyCliError(Exception):


def resolve_chain_file(args: argparse.Namespace) -> Path:
    if args.chain_file:
        return Path(args.chain_file)

    config_path = Path(args.config)
    if not config_path.is_file():
        raise VerifyCliError(
            f"No se encontró el archivo de configuración '{config_path}'. "
            "Especifica --chain-file directamente o --config con una ruta válida."
        )
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise VerifyCliError(
            f"Error de sintaxis YAML en '{config_path}': {exc}") from exc
    except OSError as exc:
        raise VerifyCliError(
            f"No fue posible leer '{config_path}': {exc}") from exc

    if not isinstance(config, dict):
        raise VerifyCliError(
            f"El archivo de configuración '{config_path}' debe contener un mapeo YAML en su raíz.")

    try:
        storage_cfg = config["storage"]
        base_path = Path(storage_cfg["base_path"])
        return base_path / storage_cfg["audit_chain_file"]
    except (KeyError, TypeError) as exc:
        raise VerifyCliError(
            f"La configuración '{config_path}' no define correctamente 'storage.audit_chain_file': {exc}") from exc


def print_human_report(result: VerificationResult, *, verbose: bool) -> None:
    separator = "=" * 70
    print(separator)
    print(" INFORME DE INTEGRIDAD - APEX SENTINEL / ANUBIS OS")
    print(separator)
    print(f" Fecha de verificación : {result.verified_at}")
    print(f" Bloques totales       : {result.total_blocks}")
    print(f" Bloques verificados   : {result.verified_blocks}")
    print(
        f" Estado de la cadena   : {'INTEGRA' if result.is_valid else 'COMPROMETIDA'}")
    print(separator)

    if result.is_valid:
        print(" No se detectaron alteraciones en la cadena de custodia.")
        if verbose:
            print(f" ({result.total_blocks} bloque(s) auditado(s) exitosamente.)")
    else:
        print(
            f" Se detectaron {len(result.failures)} bloque(s) con fallos de integridad.")
        print(f" Primer bloque afectado: #{result.first_failure_index}")
        print("-" * 70)
        for failure in result.failures:
            print(
                f" Bloque #{failure.get('index')}  [{failure.get('status', 'DESCONOCIDO')}]")
            print(f"   Archivo : {failure.get('file_path', 'N/D')}")
            for reason in failure.get("reasons", []):
                print(f"   Motivo  : {reason}")
            print("-" * 70)

    print(separator)


def print_json_report(result: VerificationResult) -> None:
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="Audita la cadena de custodia criptográfica de la evidencia forense de Anubis OS.",
    )
    parser.add_argument(
        "--config", "-c",
        default=str(Path(__file__).resolve().parent /
                    "config" / "forensics.yaml"),
        help="Ruta al archivo de configuración YAML (usado para localizar la cadena de auditoría).",
    )
    parser.add_argument(
        "--chain-file", default=None,
        help="Ruta directa al archivo audit_chain.json; si se especifica, ignora --config.",
    )
    parser.add_argument(
        "--no-check-files", action="store_true",
        help="Omite la verificación de los archivos PCAP en disco; solo audita la estructura de la cadena JSON.",
    )
    parser.add_argument("--json", action="store_true",
                        help="Emite el informe en formato JSON en lugar de texto legible.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Muestra información adicional en el informe legible.")
    return parser.parse_args()


def fail(message: str) -> NoReturn:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(EXIT_OPERATIONAL_ERROR)


def main() -> None:
    args = parse_args()

    try:
        chain_file = resolve_chain_file(args)
    except VerifyCliError as exc:
        fail(str(exc))

    if not chain_file.is_file():
        fail(f"El archivo de cadena de auditoría no existe: '{chain_file}'.")

    try:
        hash_chain = HashChainLogger(chain_file_path=chain_file)
        result = hash_chain.verify_chain(
            check_evidence_files=not args.no_check_files)
    except ChainIntegrityError as exc:
        fail(f"No fue posible auditar la cadena: {exc}")
    except Exception as exc:
        fail(f"Error inesperado durante la auditoría: {exc}")

    if args.json:
        print_json_report(result)
    else:
        print_human_report(result, verbose=args.verbose)

    sys.exit(EXIT_OK if result.is_valid else EXIT_INTEGRITY_VIOLATION)


if __name__ == "__main__":
    main()
