from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Attendance, Classroom, Student
from app.utils import get_app_tz, utc_now
from app.utils.sms_service import dispatch_sms


def _as_local(dt_utc_naive: datetime) -> datetime:
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(get_app_tz())


def calculate_attendance_status(classroom, arrival_time_utc):
    """Compare arrival (naive UTC) against classroom schedule in app local timezone."""
    arrival_local = _as_local(arrival_time_utc)
    schedule_start_local = datetime.combine(
        arrival_local.date(),
        classroom.schedule_start_time,
        tzinfo=get_app_tz(),
    )

    if arrival_local > schedule_start_local:
        delta = arrival_local - schedule_start_local
        delta_minutes = int(delta.total_seconds() // 60)
        return "Late", delta_minutes
    return "Present", 0


def process_late_alert(student, classroom, delta_minutes):
    parent_phone = student.parent.phone_number if student.parent else None
    message = f"Dear Parent, your child has arrived late to class by {delta_minutes} minutes."
    dispatch_sms(student.institution_id, parent_phone, message)


def process_absent_alert(student, classroom):
    parent_phone = student.parent.phone_number if student.parent else None
    message = "Dear Parent, your child is recorded as Absent from today's class session."
    dispatch_sms(student.institution_id, parent_phone, message)


def run_absentee_sweeper():
    now_local = _as_local(utc_now())
    today = now_local.date()
    classrooms = Classroom.query.all()

    for classroom in classrooms:
        schedule_start = datetime.combine(today, classroom.schedule_start_time, tzinfo=get_app_tz())
        sweep_threshold = schedule_start + timedelta(minutes=30)
        if now_local < sweep_threshold:
            continue

        students = Student.query.filter_by(institution_id=classroom.institution_id).all()
        for student in students:
            existing = Attendance.query.filter_by(
                student_id=student.id,
                classroom_id=classroom.id,
                date=today,
            ).first()
            if existing:
                continue

            record = Attendance(
                student_id=student.id,
                classroom_id=classroom.id,
                date=today,
                arrival_time=None,
                status="Absent",
                marked_by=None,
            )
            db.session.add(record)
            process_absent_alert(student, classroom)

    db.session.commit()
