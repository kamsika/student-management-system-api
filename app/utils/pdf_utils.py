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


def generate_attendance_summary_pdf(
    institution_name: str,
    classroom_name: str,
    date_range: str,
    total_classes_held: int,
    rows: List[Dict],
) -> bytes:
    """Printable summary PDF: Student Name, ID, Present, Absent, Percentage."""
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
    elements.append(Paragraph("Attendance Summary Report", styles["Heading2"]))
    elements.append(Paragraph(f"Classroom / Batch: {classroom_name}", styles["Normal"]))
    elements.append(Paragraph(f"Date Range: {date_range}", styles["Normal"]))
    elements.append(Paragraph(f"Total Classes Held: {total_classes_held}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    table_data = [["Student Name", "ID", "Total Present", "Total Absent", "Percentage"]]
    for row in rows:
        table_data.append([
            row.get("student_name", "") or "",
            str(row.get("registration_no", "") or row.get("student_id", "")),
            str(row.get("total_present", 0)),
            str(row.get("total_absent", 0)),
            f"{row.get('percentage', 0)}%",
        ])

    table = Table(table_data, repeatRows=1, colWidths=[55 * mm, 35 * mm, 30 * mm, 30 * mm, 28 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
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
