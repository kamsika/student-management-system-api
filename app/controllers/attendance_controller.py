from datetime import date

from app.extensions import db
from app.models import Attendance, Classroom, Student, User
from app.utils import local_today, parse_attendance_date, parse_incoming_timestamp, utc_now
from app.utils.alert_engine import calculate_attendance_status, process_late_alert


def _parse_required_date(raw_value, field_name="date"):
    if raw_value is None or str(raw_value).strip() == "":
        return None, f"{field_name} is required (YYYY-MM-DD)"
    try:
        return date.fromisoformat(str(raw_value).strip()), None
    except ValueError:
        return None, f"{field_name} must be YYYY-MM-DD"


def _authorize_classroom(classroom_id, user, *, allow_super_admin=True):
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return None, {"errors": ["Classroom not found"]}, 404

    if user.role == "teacher":
        if classroom.teacher_id != user.id or classroom.institution_id != user.institution_id:
            return None, {"errors": ["Access denied"]}, 403
    elif user.role == "institution_admin":
        if classroom.institution_id != user.institution_id:
            return None, {"errors": ["Access denied"]}, 403
    elif user.role == "super_admin":
        if not allow_super_admin:
            return None, {"errors": ["Access denied"]}, 403
    else:
        return None, {"errors": ["Access denied"]}, 403

    return classroom, None, None


def _session_dates_for_classroom(classroom_id, start_date=None, end_date=None):
    """Distinct dates when any attendance was recorded for a classroom."""
    query = db.session.query(Attendance.date).filter(Attendance.classroom_id == classroom_id)
    if start_date is not None:
        query = query.filter(Attendance.date >= start_date)
    if end_date is not None:
        query = query.filter(Attendance.date <= end_date)
    rows = query.distinct().order_by(Attendance.date.asc()).all()
    return [row[0] for row in rows]


def _attendance_percentage(present_days, total_classes):
    if not total_classes:
        return 0.0
    return round((present_days / total_classes) * 100, 1)


def _build_student_summary_for_classroom(student, classroom_id, session_dates, start_date=None, end_date=None):
    """Aggregate present/absent/% for one student against classroom session days."""
    query = Attendance.query.filter_by(student_id=student.id, classroom_id=classroom_id)
    if start_date is not None:
        query = query.filter(Attendance.date >= start_date)
    if end_date is not None:
        query = query.filter(Attendance.date <= end_date)

    records = query.all()
    present_dates = {
        record.date
        for record in records
        if record.status in ("Present", "Late")
    }
    session_set = set(session_dates)
    total_classes = len(session_set)
    total_present = len(present_dates & session_set) if session_set else len(present_dates)
    total_absent = max(total_classes - total_present, 0)
    percentage = _attendance_percentage(total_present, total_classes)

    return {
        "student_id": student.id,
        "registration_no": student.registration_no,
        "student_name": student.user.full_name if student.user else None,
        "total_classes": total_classes,
        "total_present": total_present,
        "total_absent": total_absent,
        "percentage": percentage,
    }


def _active_students_for_institution(institution_id):
    return (
        Student.query.join(User, Student.user_id == User.id)
        .filter(
            Student.institution_id == institution_id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name.asc(), Student.registration_no.asc())
        .all()
    )


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

    # Active student roster for the center (no per-classroom enrollment table yet).
    students = (
        Student.query.join(User, Student.user_id == User.id)
        .filter(
            Student.institution_id == classroom.institution_id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name.asc(), Student.registration_no.asc())
        .all()
    )
    attendance_map = {
        a.student_id: a
        for a in Attendance.query.filter_by(classroom_id=classroom_id, date=attendance_date).all()
    }

    records = []
    present_records = []
    absent_records = []

    for student in students:
        record = attendance_map.get(student.id)
        student_payload = student.to_dict()
        attendance_payload = record.to_dict() if record else None
        row = {
            "student": student_payload,
            "attendance": attendance_payload,
        }
        records.append(row)

        status = attendance_payload.get("status") if attendance_payload else None
        if status in ("Present", "Late"):
            present_records.append(row)
        else:
            # No row for the date, or explicit Absent → counted as absent.
            absent_records.append({
                "student": student_payload,
                "attendance": attendance_payload,
                "effective_status": "Absent",
            })

    total_enrolled = len(students)
    total_present = len(present_records)
    total_absent = len(absent_records)
    attendance_rate = (
        round((total_present / total_enrolled) * 100, 1) if total_enrolled else 0.0
    )

    return {
        "classroom": classroom.to_dict(),
        "date": attendance_date.isoformat(),
        "records": records,
        "present": present_records,
        "absent": absent_records,
        "summary": {
            "total_enrolled": total_enrolled,
            "total_present": total_present,
            "total_absent": total_absent,
            "attendance_rate": attendance_rate,
        },
    }, 200


def get_student_attendance(
    student_id,
    user,
    classroom_id=None,
    start_date_str=None,
    end_date_str=None,
):
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

    start_date = None
    end_date = None
    if start_date_str:
        start_date, date_error = _parse_required_date(start_date_str, "start_date")
        if date_error:
            return {"errors": [date_error]}, 400
    if end_date_str:
        end_date, date_error = _parse_required_date(end_date_str, "end_date")
        if date_error:
            return {"errors": [date_error]}, 400
    if start_date and end_date and start_date > end_date:
        return {"errors": ["start_date must be on or before end_date"]}, 400

    classroom = None
    resolved_classroom_id = None
    if classroom_id is not None and str(classroom_id).strip() != "":
        try:
            resolved_classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            return {"errors": ["classroom_id must be an integer"]}, 400
        classroom, error, status = _authorize_classroom(resolved_classroom_id, user)
        if error:
            # Parents/students can view history for their linked student but may not
            # own the classroom — allow read if the classroom is in the same center.
            if user.role in ("parent", "student"):
                classroom = Classroom.query.get(resolved_classroom_id)
                if not classroom or classroom.institution_id != student.institution_id:
                    return {"errors": ["Classroom not found"]}, 404
            else:
                return error, status

    query = Attendance.query.filter_by(student_id=student_id)
    if resolved_classroom_id is not None:
        query = query.filter_by(classroom_id=resolved_classroom_id)
    if start_date is not None:
        query = query.filter(Attendance.date >= start_date)
    if end_date is not None:
        query = query.filter(Attendance.date <= end_date)

    records = query.order_by(Attendance.date.desc(), Attendance.id.desc()).all()

    if resolved_classroom_id is not None:
        session_dates = _session_dates_for_classroom(
            resolved_classroom_id,
            start_date=start_date,
            end_date=end_date,
        )
        summary_row = _build_student_summary_for_classroom(
            student,
            resolved_classroom_id,
            session_dates,
            start_date=start_date,
            end_date=end_date,
        )
        summary = {
            "total_classes": summary_row["total_classes"],
            "total_present": summary_row["total_present"],
            "total_absent": summary_row["total_absent"],
            "percentage": summary_row["percentage"],
            "classroom_id": resolved_classroom_id,
            "classroom_name": classroom.name if classroom else None,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        }
    else:
        total_present = sum(1 for r in records if r.status in ("Present", "Late"))
        total_absent = sum(1 for r in records if r.status == "Absent")
        total_classes = len(records)
        summary = {
            "total_classes": total_classes,
            "total_present": total_present,
            "total_absent": total_absent,
            "percentage": _attendance_percentage(total_present, total_classes),
            "classroom_id": None,
            "classroom_name": None,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        }

    return {
        "student": student.to_dict(),
        "attendance": [r.to_dict() for r in records],
        "summary": summary,
    }, 200


def get_attendance_report(user, classroom_id, start_date_str, end_date_str):
    """Per-student attendance summary for a classroom over a date range."""
    if user.role not in ("teacher", "institution_admin", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    if classroom_id is None or str(classroom_id).strip() == "":
        return {"errors": ["classroom_id is required"]}, 400
    try:
        classroom_id = int(classroom_id)
    except (TypeError, ValueError):
        return {"errors": ["classroom_id must be an integer"]}, 400

    classroom, error, status = _authorize_classroom(classroom_id, user)
    if error:
        return error, status

    start_date, start_error = _parse_required_date(start_date_str, "start_date")
    if start_error:
        return {"errors": [start_error]}, 400
    end_date, end_error = _parse_required_date(end_date_str, "end_date")
    if end_error:
        return {"errors": [end_error]}, 400
    if start_date > end_date:
        return {"errors": ["start_date must be on or before end_date"]}, 400

    session_dates = _session_dates_for_classroom(
        classroom.id,
        start_date=start_date,
        end_date=end_date,
    )
    total_classes_held = len(session_dates)
    students = _active_students_for_institution(classroom.institution_id)

    rows = [
        _build_student_summary_for_classroom(
            student,
            classroom.id,
            session_dates,
            start_date=start_date,
            end_date=end_date,
        )
        for student in students
    ]

    return {
        "classroom": classroom.to_dict(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_classes_held": total_classes_held,
        "student_count": len(rows),
        "students": rows,
    }, 200
