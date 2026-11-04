from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sentinel.custody.log import CustodyLog
from sentinel.integrity.keys import KeyManager


@dataclass
class ReportMetadata:
    report_id: str
    generated_at: str
    operator_id: str
    workspace: str
    total_entries: int
    chain_valid: bool


def generate_report(
    workspace: Path | str,
    operator_id: str,
    output_path: Path | str | None = None,
) -> Path:

    ws = Path(workspace)
    custody_path = ws / "custody.log"

    if not custody_path.exists():
        raise FileNotFoundError(f"No custody log found at {custody_path}")

    km = KeyManager.load(operator_id, operator_id)
    custody_log = CustodyLog(custody_path)

    report = custody_log.verify_chain(
        operators={km.identity.operator_id: km.identity}
    )

    entries = custody_log.read_all()

    now = datetime.now(UTC).isoformat()
    metadata = ReportMetadata(
        report_id=f"REP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        generated_at=now,
        operator_id=operator_id,
        workspace=str(ws.resolve()),
        total_entries=len(entries),
        chain_valid=report.valid,
    )

    report_data = {
        "metadata": asdict(metadata),
        "integrity_summary": {
            "valid_entries": report.valid_entries,
            "issues": [asdict(i) for i in report.issues],
            "head_hash": report.head_hash,
        },
        "timeline": entries,
    }

    if output_path is None:
        output_path = ws / f"report_{metadata.report_id}.json"
    else:
        output_path = Path(output_path)

    output_path.write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output_path
