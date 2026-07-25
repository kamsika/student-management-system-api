"""Parent-facing authentication and attendance endpoints."""

import calendar
from datetime import date

from flask_jwt_extended import create_access_token
from sqlalchemy import extract

from app.models import Attendance, Student, User
from app.utils.phone_utils import digits_only, mask_phone, phone_matches

_digits_only = digits_only
_phone_matches = phone_matches


def parent_login(data):
    phone = (data.get("phone_number") or data.get("phone") or "").strip()
    password = data.get("password")
    password = "" if password is None else str(password)

    normalized = digits_only(phone)
    print(
        f"[PARENT AUTH] Login attempt phone={mask_phone(phone)} "
        f"normalized_len={len(normalized)} password_len={len(password)}"
    )

    if not phone or not password:
        print("[PARENT AUTH] Login failed: missing phone number or password")
        return {"errors": ["Phone number and password are required"]}, 400

    candidates = User.query.filter(User.role == "parent", User.phone_number.isnot(None)).all()
    print(f"[PARENT AUTH] Checking against {len(candidates)} parent account(s) with a phone number")

    phone_matched = [c for c in candidates if phone_matches(c.phone_number, phone)]
    if not phone_matched:
        print(
            f"[PARENT AUTH] Login failed: no parent account matches phone={mask_phone(phone)}. "
            "Verify the parent exists and that Student.parent_id links to it."
        )
        return {"errors": ["Invalid phone number or password"]}, 401

    print(f"[PARENT AUTH] {len(phone_matched)} account(s) matched the phone number")

    matched = next((c for c in phone_matched if c.check_password(password)), None)
    if not matched:
        print(
            f"[PARENT AUTH] Login failed: password mismatch for user_id(s)="
            f"{[c.id for c in phone_matched]}. Phone matched but the password hash did not verify."
        )
        return {"errors": ["Invalid phone number or password"]}, 401

    if not matched.is_active:
        print(f"[PARENT AUTH] Login failed: account deactivated user_id={matched.id}")
        return {"errors": ["Account is deactivated"]}, 403

    if matched.institution and matched.institution.status == "Suspended":
        print(
            f"[PARENT AUTH] Login failed: institution suspended "
            f"institution_id={matched.institution_id}"
        )
        return {"errors": ["Institution is suspended"]}, 403

    linked_children = Student.query.filter_by(parent_id=matched.id).count()
    if linked_children == 0:
        print(
            f"[PARENT AUTH] Warning: user_id={matched.id} has no linked students; "
            "the dashboard will be empty until a Student row points at this parent."
        )

    print(
        f"[PARENT AUTH] Login success user_id={matched.id} "
        f"institution_id={matched.institution_id} linked_children={linked_children}"
    )

    token = create_access_token(
        identity=str(matched.id),
        additional_claims={
            "role": matched.role,
            "institution_id": matched.institution_id,
        },
    )
    return {
        "access_token": token,
        "user": matched.to_dict(include_institution=True),
    }, 200


def get_parent_children(user):
    if user.role != "parent":
        return {"errors": ["Access denied"]}, 403
    students = Student.query.filter_by(parent_id=user.id).all()
    return {"students": [s.to_dict() for s in students]}, 200


def _resolve_child(user, student_id):
    query = Student.query.filter_by(parent_id=user.id)
    if student_id is not None and str(student_id).strip() != "":
        try:
            student = query.filter_by(id=int(student_id)).first()
        except (TypeError, ValueError):
            return None, ({"errors": ["student_id must be an integer"]}, 400)
        if not student:
            return None, ({"errors": ["Student not found or not linked to this parent"]}, 404)
        return student, None

    student = query.order_by(Student.id.asc()).first()
    if not student:
        return None, ({"errors": ["No student linked to this parent"]}, 404)
    return student, None


def get_parent_attendance(user, student_id=None, month=None, year=None):
    if user.role != "parent":
        return {"errors": ["Access denied"]}, 403

    student, error = _resolve_child(user, student_id)
    if error:
        return error

    today = date.today()
    try:
        month = int(month) if month else today.month
        year = int(year) if year else today.year
    except (TypeError, ValueError):
        return {"errors": ["month and year must be integers"]}, 400

    if month < 1 or month > 12:
        return {"errors": ["month must be between 1 and 12"]}, 400
    if year < 2000 or year > 2100:
        return {"errors": ["year is out of range"]}, 400

    records = (
        Attendance.query.filter(
            Attendance.student_id == student.id,
            extract("year", Attendance.date) == year,
            extract("month", Attendance.date) == month,
        )
        .order_by(Attendance.date.asc(), Attendance.id.asc())
        .all()
    )

    days = []
    present = late = absent = 0
    for record in records:
        status = record.status
        if status == "Present":
            present += 1
        elif status == "Late":
            late += 1
        elif status == "Absent":
            absent += 1
        days.append(
            {
                "date": record.date.isoformat(),
                "status": status,
                "arrival_time": record.arrival_time.isoformat() if record.arrival_time else None,
            }
        )

    marked_days = present + late + absent
    percentage = round(((present + late) / marked_days) * 100, 1) if marked_days else 0.0

    return {
        "student": student.to_dict(),
        "month": month,
        "year": year,
        "days_in_month": calendar.monthrange(year, month)[1],
        "records": days,
        "summary": {
            "total_present": present,
            "total_late": late,
            "total_absent": absent,
            "total_marked": marked_days,
            "percentage": percentage,
        },
    }, 200
