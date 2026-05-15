from __future__ import annotations

from fpdf import FPDF
from datetime import datetime
import os


class ReportGenerator:
    def __init__(self, operador="Sentinel"):
        self.operador = operador

    def generar_pdf_forense(self, tipo_dato, datos, output_path):
        pdf = FPDF()
        pdf.add_page()

        # --- ENCABEZADO TÁCTICO ---
        pdf.set_fill_color(30, 30, 30)
        pdf.rect(0, 0, 210, 40, 'F')
        pdf.set_font("Arial", 'B', 16)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 10, f"ANUBIS OS - REPORTE DE EXTRACCIÓN", ln=True, align='C')
        pdf.set_font("Arial", '', 10)
        pdf.cell(
            0, 10, f"Operador: {self.operador} | Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
        pdf.ln(20)

        # --- CUERPO DEL REPORTE ---
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f"EVIDENCIA RECOLECTADA: {tipo_dato.upper()}", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

        pdf.set_font("Arial", '', 9)

        if tipo_dato == "WhatsApp":
            for msg in datos:
                # msg = (remitente, texto, fecha, es_mio)
                remitente = "YO" if msg[3] == 1 else msg[0]
                texto = f"[{msg[2]}] {remitente}: {msg[1]}"
                pdf.multi_cell(0, 8, texto.encode(
                    'latin-1', 'replace').decode('latin-1'))
                pdf.ln(2)

        elif tipo_dato == "Chrome":
            for item in datos:
                # item = (url, titulo, fecha)
                linea = f"URL: {item[0][:80]}... | Título: {item[1]}"
                pdf.multi_cell(0, 8, linea.encode(
                    'latin-1', 'replace').decode('latin-1'))
                pdf.ln(2)

        # --- PIE DE PÁGINA ---
        filename = f"Reporte_{tipo_dato}_{datetime.now().strftime('%H%M%S')}.pdf"
        final_path = os.path.join(output_path, filename)
        pdf.output(final_path)
        return final_path
