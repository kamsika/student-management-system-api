from app.extensions import db
from app.models import Attendance, Classroom, Student
from app.utils import local_today, parse_incoming_timestamp, utc_now
from app.utils.alert_engine import calculate_attendance_status, process_late_alert


def _resolve_teacher_classroom(user, classroom_id=None):
    if not user.institution_id:
        return None, {"errors": ["Teacher is not linked to a center"]}, 400

    if classroom_id:
        classroom = Classroom.query.get(classroom_id)
        if not classroom:
            return None, {"errors": ["Classroom not found"]}, 404
        if classroom.institution_id != user.institution_id:
            return None, {"errors": ["Access denied"]}, 403
        if classroom.teacher_id != user.id:
            return None, {"errors": ["Access denied"]}, 403
        return classroom, None, None

    classroom = (
        Classroom.query.filter_by(teacher_id=user.id, institution_id=user.institution_id)
        .order_by(Classroom.name)
        .first()
    )
    if not classroom:
        return None, {"errors": ["No classroom assigned. Ask your center admin to create one."]}, 400
    return classroom, None, None


def _find_student_in_center(institution_id, scanned_id):
    """Resolve a scanned QR value to a student in the given center.

    Accepts:
    - registration codes like "STU-2026-003"
    - numeric primary keys like "12"
    """
    scanned = (str(scanned_id) if scanned_id is not None else "").strip()
    if not scanned or not institution_id:
        return None

    # 1) Prefer exact registration_no match (custom IDs from QR codes).
    student = Student.query.filter_by(
        institution_id=institution_id,
        registration_no=scanned,
    ).first()
    if student:
        print(
            f"[ATTENDANCE] Matched registration_no={scanned!r} -> "
            f"student.id={student.id} name={student.user.full_name if student.user else None!r}"
        )
        return student

    # 2) If the scanned value is a pure integer, try DB primary key.
    if scanned.isdigit():
        student = Student.query.filter_by(
            institution_id=institution_id,
            id=int(scanned),
        ).first()
        if student:
            print(
                f"[ATTENDANCE] Matched numeric id={scanned!r} -> "
                f"student.id={student.id} registration_no={student.registration_no!r} "
                f"name={student.user.full_name if student.user else None!r}"
            )
            return student

    print(f"[ATTENDANCE] No student found in institution_id={institution_id} for scanned_id={scanned!r}")
    return None


def mark_attendance(data, user):
    raw_student_id = data.get("student_id")
    registration_no = (data.get("registration_no") or "").strip()
    classroom_id = data.get("classroom_id")
    status_override = data.get("status")

    # Support both student_id (exact scanned QR text) and registration_no.
    scanned_id = ""
    if raw_student_id is not None and str(raw_student_id).strip():
        scanned_id = str(raw_student_id).strip()
    elif registration_no:
        scanned_id = registration_no

    print(
        f"[ATTENDANCE] Received attendance request for ID: {scanned_id!r} "
        f"(raw student_id={raw_student_id!r}, registration_no={registration_no!r})"
    )

    if not classroom_id:
        return {"errors": ["classroom_id is required"]}, 400

    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return {"errors": ["Classroom not found"]}, 404

    if user.role == "teacher":
        if classroom.teacher_id != user.id or classroom.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403

    if not scanned_id:
        return {"errors": ["student_id or registration_no is required"]}, 400

    student = _find_student_in_center(classroom.institution_id, scanned_id)
    if not student:
        return {"errors": [f"Student not found for ID: {scanned_id}"]}, 404

    today = local_today()

    # Prefer accurate server UTC time; accept client scanned_at only as a fallback hint.
    scanned_at_raw = data.get("scanned_at")
    if scanned_at_raw:
        arrival_time = parse_incoming_timestamp(scanned_at_raw)
    else:
        arrival_time = utc_now()

    print(f"[ATTENDANCE] Recording arrival_time(UTC)={arrival_time.isoformat()}Z local_date={today.isoformat()}")

    if status_override in ("Present", "Absent", "Late"):
        status = status_override
        delta_minutes = 0
    else:
        status, delta_minutes = calculate_attendance_status(classroom, arrival_time)

    try:
        record = Attendance.query.filter_by(
            student_id=student.id,
            classroom_id=classroom.id,
            date=today,
        ).first()

        if record:
            record.status = status
            record.arrival_time = arrival_time if status != "Absent" else None
            record.marked_by = user.id
        else:
            record = Attendance(
                student_id=student.id,
                classroom_id=classroom.id,
                date=today,
                arrival_time=arrival_time if status != "Absent" else None,
                status=status,
                marked_by=user.id,
            )
            db.session.add(record)

        if status == "Late":
            process_late_alert(student, classroom, delta_minutes)

        db.session.commit()
        db.session.refresh(record)

        payload = record.to_dict()
        print(
            f"[ATTENDANCE] Marked present student_id={student.id} "
            f"registration_no={student.registration_no!r} "
            f"name={payload.get('student_name')!r} status={status}"
        )
        return {"attendance": payload, "delta_minutes": delta_minutes}, 200
    except Exception as exc:
        db.session.rollback()
        print(f"[ATTENDANCE] mark_attendance failed: {exc}")
        return {"errors": ["Failed to mark attendance"]}, 500


def scan_center_attendance(data, user):
    """Mark attendance by QR value for the teacher's own center only."""
    if user.role != "teacher":
        return {"errors": ["Only teachers can use the live scanner"]}, 403

    raw_student_id = data.get("student_id")
    registration_no = (data.get("registration_no") or "").strip()
    scanned_id = ""
    if raw_student_id is not None and str(raw_student_id).strip():
        scanned_id = str(raw_student_id).strip()
    elif registration_no:
        scanned_id = registration_no

    print(f"[ATTENDANCE] Received attendance request for ID: {scanned_id!r}")

    if not scanned_id:
        return {"errors": ["student_id is required (scanned QR value)"]}, 400

    classroom, error, status = _resolve_teacher_classroom(user, data.get("classroom_id"))
    if error:
        return error, status

    student = _find_student_in_center(user.institution_id, scanned_id)
    if not student:
        return {"errors": [f"Student not found in your center: {scanned_id}"]}, 404

    payload = {
        # Keep the original scanned QR text — do not replace with another student's id.
        "student_id": scanned_id,
        "classroom_id": classroom.id,
        "status": data.get("status") or "Present",
        "scanned_at": data.get("scanned_at"),
    }
    return mark_attendance(payload, user)


def get_today_center_attendance(user):
    """List students from the teacher's center who were scanned today."""
    if user.role != "teacher":
        return {"errors": ["Access denied"]}, 403
    if not user.institution_id:
        return {"errors": ["Teacher is not linked to a center"]}, 400

    today = local_today()
    records = (
        Attendance.query.join(Student, Attendance.student_id == Student.id)
        .join(Classroom, Attendance.classroom_id == Classroom.id)
        .filter(
            Student.institution_id == user.institution_id,
            Classroom.institution_id == user.institution_id,
            Attendance.date == today,
            Attendance.status.in_(("Present", "Late")),
        )
        .order_by(Attendance.arrival_time.desc(), Attendance.id.desc())
        .all()
    )

    return {
        "date": today.isoformat(),
        "institution_id": user.institution_id,
        "count": len(records),
        "records": [r.to_dict() for r in records],
    }, 200


def get_classroom_attendance(classroom_id, user):
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return {"errors": ["Classroom not found"]}, 404

    if user.role == "teacher":
        if classroom.teacher_id != user.id or classroom.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
    if user.role == "institution_admin" and classroom.institution_id != user.institution_id:
        return {"errors": ["Access denied"]}, 403

    today = local_today()
    students = Student.query.filter_by(institution_id=classroom.institution_id).all()
    attendance_map = {
        a.student_id: a
        for a in Attendance.query.filter_by(classroom_id=classroom_id, date=today).all()
    }

    result = []
    for student in students:
        record = attendance_map.get(student.id)
        result.append({
            "student": student.to_dict(),
            "attendance": record.to_dict() if record else None,
        })

    return {
        "classroom": classroom.to_dict(),
        "date": today.isoformat(),
        "records": result,
    }, 200


def get_student_attendance(student_id, user):
    student = Student.query.get(student_id)
    if not student:
        return {"errors": ["Student not found"]}, 404

    if user.role == "student":
        if not user.student_profile or user.student_profile.id != student_id:
            return {"errors": ["Access denied"]}, 403
    elif user.role == "parent":
        if student.parent_id != user.id:
            return {"errors": ["Access denied"]}, 403
    elif user.role == "institution_admin":
        if student.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
    elif user.role == "teacher":
        if student.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
    elif user.role != "super_admin":
        return {"errors": ["Access denied"]}, 403

    records = Attendance.query.filter_by(student_id=student_id).order_by(
        Attendance.date.desc()
    ).limit(50).all()

    return {
        "student": student.to_dict(),
        "attendance": [r.to_dict() for r in records],
    }, 200
