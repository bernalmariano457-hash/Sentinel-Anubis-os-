from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from sentinel.custody.log import CustodyAction, CustodyLog
from sentinel.integrity.hashing import hash_file
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.signing import sign_artifact_manifest, write_signature
from sentinel.integrity.timestamp import TimeResolver

logger = logging.getLogger(__name__)


def register_evidence(
    workspace: Path,
    operator_id: str,
    artifact_path: Path,
    artifact_type: str,
    details: dict[str, Any] | None = None,
) -> Path:

    if not artifact_path.exists():
        raise FileNotFoundError(f"El artefacto no existe: {artifact_path}")

    try:
        km = KeyManager.load(operator_id, operator_id)

        ts = TimeResolver().now()

        artifact_id = str(uuid.uuid4())
        evidence_root = workspace / "data" / "evidence"
        artifact_dir = evidence_root / f"art-{artifact_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        final_data_path = artifact_dir / artifact_path.name
        shutil.move(str(artifact_path), str(final_data_path))

        manifest_data = {
            "schema_version": "1.0",
            "artifact_id": artifact_id,
            "type": artifact_type,
            "operator_id": operator_id,
            "created_at": ts.iso_utc,
            "time_source": ts.source.value,
            "time_uncertainty_ms": ts.uncertainty_ms,
            "file": {
                "name": final_data_path.name,
                "size_bytes": final_data_path.stat().st_size,
                "sha256": hash_file(final_data_path),
            },
        }

        if details:
            manifest_data["details"] = details

        sig = sign_artifact_manifest(km, manifest_data)
        manifest_data["signature"] = sig.to_dict()

        (artifact_dir / "manifest.json").write_text(
            json.dumps(manifest_data, indent=2), encoding="utf-8"
        )
        write_signature(artifact_dir / "signature.sig", sig)

        custody = CustodyLog(workspace / "custody.log")
        custody.append(
            operator=km,
            action=CustodyAction.CREATE,
            timestamp=ts,
            artifact_id=artifact_id,
            details={"type": artifact_type, "dir": artifact_dir.name},
        )

        logger.info(f"Evidencia registrada en custodia: {artifact_dir.name}")
        return artifact_dir

    except Exception as e:
        logger.error(f"Fallo al registrar evidencia {artifact_path.name}: {e}")
        raise RuntimeError(f"No se pudo proteger la evidencia: {e}") from e
