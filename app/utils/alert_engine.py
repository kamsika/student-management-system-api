from datetime import datetime, timedelta

from app.extensions import db
from app.models import Attendance, Classroom, Student
from app.utils import utc_now
from app.utils.sms_service import dispatch_sms


def calculate_attendance_status(classroom, arrival_time):
    schedule_start = datetime.combine(arrival_time.date(), classroom.schedule_start_time)
    if arrival_time > schedule_start:
        delta = arrival_time - schedule_start
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
    now = utc_now()
    today = now.date()
    classrooms = Classroom.query.all()

    for classroom in classrooms:
        schedule_start = datetime.combine(today, classroom.schedule_start_time)
        sweep_threshold = schedule_start + timedelta(minutes=30)
        if now < sweep_threshold:
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
