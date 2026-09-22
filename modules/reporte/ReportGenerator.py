from __future__ import annotations

import os
from datetime import datetime

from fpdf import FPDF


class ReportGenerator:

    def __init__(self, operador: str = "Sentinel"):
        self.operador = operador

    def generar_pdf_forense(self, tipo_dato: str, datos: list, output_path: str) -> str:
        pdf = FPDF()
        pdf.add_page()

        # --- ENCABEZADO ---
        pdf.set_fill_color(30, 30, 30)
        pdf.rect(0, 0, 210, 40, "F")
        pdf.set_font("Arial", "B", 16)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 10, "ANUBIS OS - REPORTE DE EXTRACCIÓN", ln=True, align="C")
        pdf.set_font("Arial", "", 10)
        pdf.cell(
            0,
            10,
            f"Operador: {self.operador} | Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            ln=True,
            align="C",
        )
        pdf.ln(20)

        # --- CUERPO ---
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, f"EVIDENCIA RECOLECTADA: {tipo_dato.upper()}", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)
        pdf.set_font("Arial", "", 9)

        if tipo_dato == "WhatsApp":
            for msg in datos:
                remitente = "YO" if msg[3] == 1 else str(msg[0])
                texto = f"[{msg[2]}] {remitente}: {msg[1]}"
                pdf.multi_cell(0, 8, texto.encode("utf-8", "replace").decode("utf-8"))
                pdf.ln(2)

        elif tipo_dato == "Chrome":
            for item in datos:
                linea = f"URL: {str(item[0])[:80]}... | Título: {item[1]}"
                pdf.multi_cell(0, 8, linea.encode("utf-8", "replace").decode("utf-8"))
                pdf.ln(2)

        # --- GUARDAR ---
        filename = f"Reporte_{tipo_dato}_{datetime.now().strftime('%H%M%S')}.pdf"
        final_path = os.path.join(output_path, filename)
        pdf.output(final_path)
        return final_path
