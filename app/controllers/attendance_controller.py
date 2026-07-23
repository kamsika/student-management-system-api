from datetime import datetime

from app.extensions import db
from app.models import Attendance, Classroom, Student
from app.utils import utc_now
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


def mark_attendance(data, user):
    student_id = data.get("student_id")
    registration_no = (data.get("registration_no") or "").strip()
    classroom_id = data.get("classroom_id")
    status_override = data.get("status")

    if not classroom_id:
        return {"errors": ["classroom_id is required"]}, 400

    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return {"errors": ["Classroom not found"]}, 404

    if user.role == "teacher":
        if classroom.teacher_id != user.id or classroom.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403

    student = None
    if student_id:
        student = Student.query.get(student_id)
    elif registration_no:
        student = Student.query.filter_by(
            institution_id=classroom.institution_id,
            registration_no=registration_no,
        ).first()

    if not student_id and not registration_no:
        return {"errors": ["student_id or registration_no is required"]}, 400

    if not student or student.institution_id != classroom.institution_id:
        return {"errors": ["Student not found"]}, 404

    student_id = student.id
    today = utc_now().date()

    scanned_at_raw = data.get("scanned_at")
    if scanned_at_raw:
        try:
            arrival_time = datetime.fromisoformat(str(scanned_at_raw).replace("Z", "+00:00"))
            if arrival_time.tzinfo is not None:
                arrival_time = arrival_time.replace(tzinfo=None)
        except (TypeError, ValueError):
            arrival_time = utc_now()
    else:
        arrival_time = utc_now()

    if status_override in ("Present", "Absent", "Late"):
        status = status_override
        delta_minutes = 0
    else:
        status, delta_minutes = calculate_attendance_status(classroom, arrival_time)

    try:
        record = Attendance.query.filter_by(
            student_id=student_id,
            classroom_id=classroom_id,
            date=today,
        ).first()

        if record:
            record.status = status
            record.arrival_time = arrival_time if status != "Absent" else None
            record.marked_by = user.id
        else:
            record = Attendance(
                student_id=student_id,
                classroom_id=classroom_id,
                date=today,
                arrival_time=arrival_time if status != "Absent" else None,
                status=status,
                marked_by=user.id,
            )
            db.session.add(record)

        if status == "Late":
            process_late_alert(student, classroom, delta_minutes)

        db.session.commit()
        return {"attendance": record.to_dict(), "delta_minutes": delta_minutes}, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to mark attendance"]}, 500


def scan_center_attendance(data, user):
    """Mark attendance by QR/registration for the teacher's own center only."""
    if user.role != "teacher":
        return {"errors": ["Only teachers can use the live scanner"]}, 403

    registration_no = (data.get("registration_no") or "").strip()
    if not registration_no:
        return {"errors": ["registration_no is required"]}, 400

    classroom, error, status = _resolve_teacher_classroom(user, data.get("classroom_id"))
    if error:
        return error, status

    student = Student.query.filter_by(
        institution_id=user.institution_id,
        registration_no=registration_no,
    ).first()
    if not student:
        return {"errors": [f"Student not found in your center: {registration_no}"]}, 404

    payload = {
        "registration_no": registration_no,
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

    today = utc_now().date()
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

    today = utc_now().date()
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
