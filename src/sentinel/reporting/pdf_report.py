from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_pdf_report(json_report_path: Path | str, output_pdf_path: Path | str) -> Path:

    json_path = Path(json_report_path)
    pdf_path = Path(output_pdf_path)

    if not json_path.exists():
        raise FileNotFoundError(f"JSON report not found: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    meta = data["metadata"]
    integrity = data["integrity_summary"]
    timeline = data["timeline"]

    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Heading1'], fontSize=18, spaceAfter=20
    )
    subtitle_style = ParagraphStyle(
        'CustomSubtitle', parent=styles['Heading2'], fontSize=14, spaceAfter=10
    )

    elements = []

    elements.append(Paragraph("APEX SENTINEL - FORENSIC REPORT", title_style))
    elements.append(
        Paragraph(f"Report ID: {meta['report_id']}", styles['Normal']))
    elements.append(
        Paragraph(f"Generated At: {meta['generated_at']}", styles['Normal']))
    elements.append(
        Paragraph(f"Operator ID: {meta['operator_id']}", styles['Normal']))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Integrity Summary", subtitle_style))
    status_color = "green" if meta['chain_valid'] else "red"
    status_text = "VALID" if meta['chain_valid'] else "COMPROMISED"

    elements.append(Paragraph(
        f"Chain Status: <font color='{status_color}'><b>{status_text}</b></font>", styles['Normal']))
    elements.append(
        Paragraph(f"Total Entries: {meta['total_entries']}", styles['Normal']))
    elements.append(
        Paragraph(f"Head Hash: {integrity['head_hash']}", styles['Normal']))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Evidence Timeline", subtitle_style))

    table_data = [["Seq", "Timestamp (UTC)", "Action", "Artifact / Details"]]

    for entry in timeline:
        details = entry.get("details") or {}
        artifact = entry.get("artifact_id") or "N/A"
        detail_str = ", ".join(
            f"{k}={v}" for k, v in details.items() if k not in ('blob', 'included'))
        action = entry.get("action", "unknown")
        ts = entry.get("timestamp", "")

        table_data.append([
            str(entry.get("seq", "")),
            ts,
            action.upper(),
            f"Artifact: {artifact}\n{detail_str}"
        ])

    t = Table(table_data, colWidths=[30, 130, 70, 250])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(t)
    elements.append(Spacer(1, 30))

    elements.append(Paragraph(
        "This document was generated automatically by APEX SENTINEL. The integrity of the evidence listed above is cryptographically verifiable.", styles['Italic']))

    doc.build(elements)
    return pdf_path
