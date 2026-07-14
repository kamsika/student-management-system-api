import io
import uuid
from datetime import datetime
from typing import List, Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet


def generate_attendance_pdf(
    institution_name: str,
    classroom_name: str,
    date_range: str,
    records: List[Dict],
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"<b>{institution_name}</b>", styles["Title"]))
    elements.append(Paragraph(f"Classroom: {classroom_name}", styles["Heading2"]))
    elements.append(Paragraph(f"Date Range: {date_range}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    table_data = [["Date", "Student Id", "Registration", "Name", "Timestamp", "Status"]]
    for record in records:
        table_data.append([
            record.get("date", ""),
            str(record.get("student_id", "")),
            record.get("registration_no", ""),
            record.get("student_name", ""),
            record.get("arrival_time", "") or "-",
            record.get("status", ""),
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))

    verification_code = str(uuid.uuid4())[:8].upper()
    elements.append(Paragraph(
        f"Generated: {datetime.utcnow().isoformat()} UTC | Verification Code: {verification_code}",
        styles["Normal"],
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()
