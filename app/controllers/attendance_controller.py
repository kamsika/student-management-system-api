from app.extensions import db
from app.models import Attendance, Classroom, Student
from app.utils import local_today, parse_attendance_date, parse_incoming_timestamp, utc_now
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
    prevent_duplicate = bool(data.get("prevent_duplicate"))

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

    attendance_date, date_error = parse_attendance_date(data.get("date"))
    if date_error:
        return {"errors": [date_error]}, 400
    # Scans always use the live calendar day; optional date is for future tooling only.
    if prevent_duplicate:
        attendance_date = local_today()

    # Prefer accurate server UTC time; accept client scanned_at only as a fallback hint.
    scanned_at_raw = data.get("scanned_at")
    if scanned_at_raw:
        arrival_time = parse_incoming_timestamp(scanned_at_raw)
    else:
        arrival_time = utc_now()

    print(
        f"[ATTENDANCE] Recording arrival_time(UTC)={arrival_time.isoformat()}Z "
        f"local_date={attendance_date.isoformat()}"
    )

    if status_override in ("Present", "Absent", "Late"):
        status = status_override
        delta_minutes = 0
    else:
        status, delta_minutes = calculate_attendance_status(classroom, arrival_time)

    try:
        record = Attendance.query.filter_by(
            student_id=student.id,
            classroom_id=classroom.id,
            date=attendance_date,
        ).first()

        if record and prevent_duplicate and record.status in ("Present", "Late"):
            payload = record.to_dict()
            print(
                f"[ATTENDANCE] Duplicate scan blocked student_id={student.id} "
                f"registration_no={student.registration_no!r} date={attendance_date.isoformat()}"
            )
            return {
                "errors": ["Already scanned for today!"],
                "already_scanned": True,
                "attendance": payload,
            }, 409

        if record:
            record.status = status
            record.arrival_time = arrival_time if status != "Absent" else None
            record.marked_by = user.id
        else:
            record = Attendance(
                student_id=student.id,
                classroom_id=classroom.id,
                date=attendance_date,
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
        "prevent_duplicate": True,
    }
    return mark_attendance(payload, user)


def get_center_attendance(user, date_str=None, classroom_id=None):
    """List Present/Late attendance for a center on a given date (default: today)."""
    if user.role not in ("teacher", "institution_admin", "super_admin"):
        return {"errors": ["Access denied"]}, 403
    if user.role != "super_admin" and not user.institution_id:
        return {"errors": ["User is not linked to a center"]}, 400

    attendance_date, date_error = parse_attendance_date(date_str)
    if date_error:
        return {"errors": [date_error]}, 400

    query = (
        Attendance.query.join(Student, Attendance.student_id == Student.id)
        .join(Classroom, Attendance.classroom_id == Classroom.id)
        .filter(
            Attendance.date == attendance_date,
            Attendance.status.in_(("Present", "Late")),
        )
    )

    if user.role == "super_admin":
        if classroom_id:
            query = query.filter(Attendance.classroom_id == int(classroom_id))
    else:
        query = query.filter(
            Student.institution_id == user.institution_id,
            Classroom.institution_id == user.institution_id,
        )
        if classroom_id:
            classroom = Classroom.query.get(int(classroom_id))
            if not classroom or classroom.institution_id != user.institution_id:
                return {"errors": ["Classroom not found"]}, 404
            if user.role == "teacher" and classroom.teacher_id != user.id:
                return {"errors": ["Access denied"]}, 403
            query = query.filter(Attendance.classroom_id == classroom.id)
        elif user.role == "teacher":
            # Teachers only see attendance for classrooms they teach.
            query = query.filter(Classroom.teacher_id == user.id)

    records = query.order_by(Attendance.arrival_time.desc(), Attendance.id.desc()).all()

    return {
        "date": attendance_date.isoformat(),
        "institution_id": user.institution_id,
        "classroom_id": int(classroom_id) if classroom_id else None,
        "count": len(records),
        "records": [r.to_dict() for r in records],
    }, 200


def get_today_center_attendance(user, date_str=None, classroom_id=None):
    """Backward-compatible alias for get_center_attendance."""
    return get_center_attendance(user, date_str=date_str, classroom_id=classroom_id)


def get_classroom_attendance(classroom_id, user, date_str=None):
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return {"errors": ["Classroom not found"]}, 404

    if user.role == "teacher":
        if classroom.teacher_id != user.id or classroom.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
    if user.role == "institution_admin" and classroom.institution_id != user.institution_id:
        return {"errors": ["Access denied"]}, 403

    attendance_date, date_error = parse_attendance_date(date_str)
    if date_error:
        return {"errors": [date_error]}, 400

    students = Student.query.filter_by(institution_id=classroom.institution_id).all()
    attendance_map = {
        a.student_id: a
        for a in Attendance.query.filter_by(classroom_id=classroom_id, date=attendance_date).all()
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
        "date": attendance_date.isoformat(),
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
