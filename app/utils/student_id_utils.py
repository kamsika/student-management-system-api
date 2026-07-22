import re
from datetime import datetime


def generate_next_registration_no(institution_id: int) -> str:
    from app.models import Student

    year = datetime.utcnow().year
    prefix = f"STU-{year}-"
    pattern = re.compile(rf"^STU-{year}-(\d+)$", re.IGNORECASE)

    max_seq = 0
    students = Student.query.filter_by(institution_id=institution_id).all()
    for student in students:
        match = pattern.match(student.registration_no or "")
        if match:
            max_seq = max(max_seq, int(match.group(1)))

    return f"{prefix}{max_seq + 1:03d}"


def build_placeholder_emails(registration_no: str, subdomain: str) -> tuple[str, str]:
    base = registration_no.lower().replace(" ", "")
    safe_subdomain = re.sub(r"[^\w-]", "", subdomain.lower()) or "school"
    student_email = f"{base}@{safe_subdomain}.student.local"
    parent_email = f"{base}.parent@{safe_subdomain}.student.local"
    return student_email, parent_email
