import csv
import io
from typing import List, Dict


def parse_students_csv(file_content: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(file_content))
    required = {"registration_no", "full_name", "email", "parent_name", "parent_phone", "parent_email"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV must contain columns: registration_no, full_name, email, parent_name, parent_phone, parent_email")
    rows = []
    for row in reader:
        if not row.get("registration_no"):
            continue
        rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def generate_students_template_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "registration_no",
            "full_name",
            "email",
            "contact",
            "grade",
            "section",
            "gender",
            "parent_name",
            "parent_phone",
            "parent_email",
        ]
    )
    writer.writerow(
        [
            "STU-2026-001",
            "Kavisan Selvam",
            "kavisan@test.com",
            "+94771234567",
            "10",
            "A",
            "Male",
            "Selvam Arumugam",
            "+94777123456",
            "selvam@test.com",
        ]
    )
    writer.writerow(
        [
            "STU-2026-002",
            "Abiraami Balan",
            "abiraami@test.com",
            "+94772345678",
            "10",
            "A",
            "Female",
            "Balan Rajan",
            "+94777654321",
            "balan@test.com",
        ]
    )
    return output.getvalue()


def export_attendance_csv(records: List[Dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Student Id", "Registration Code", "Name", "Timestamp", "Status"])
    for record in records:
        writer.writerow([
            record.get("date", ""),
            record.get("student_id", ""),
            record.get("registration_no", ""),
            record.get("student_name", ""),
            record.get("arrival_time", ""),
            record.get("status", ""),
        ])
    return output.getvalue()


def export_attendance_summary_csv(rows: List[Dict]) -> str:
    """CSV/Excel-friendly summary: Name, ID, Present, Absent, Percentage."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Name", "ID", "Total Present", "Total Absent", "Percentage"])
    for row in rows:
        writer.writerow([
            row.get("student_name", "") or "",
            row.get("registration_no", "") or row.get("student_id", ""),
            row.get("total_present", 0),
            row.get("total_absent", 0),
            row.get("percentage", 0),
        ])
    return output.getvalue()
