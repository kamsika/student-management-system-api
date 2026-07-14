from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.models import Student, StudyLog
from app.utils import utc_now


def toggle_study_session(user):
    student = Student.query.filter_by(user_id=user.id).first()
    if not student:
        return {"errors": ["Student profile not found"]}, 404

    active = StudyLog.query.filter_by(student_id=student.id, end_time=None).first()

    try:
        if active:
            now = utc_now()
            active.end_time = now
            delta = now - active.start_time
            active.duration_minutes = max(1, int(delta.total_seconds() // 60))
            db.session.commit()
            return {"study_log": active.to_dict(), "action": "stopped"}, 200

        log = StudyLog(student_id=student.id, start_time=utc_now())
        db.session.add(log)
        db.session.commit()
        return {"study_log": log.to_dict(), "action": "started"}, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to toggle study session"]}, 500


def get_study_analytics(user, days=30):
    student = None
    if user.role == "student":
        student = Student.query.filter_by(user_id=user.id).first()
    elif user.role == "institution_admin":
        student_id = None
        return _analytics_for_institution(user.institution_id, days)

    if not student:
        return {"errors": ["Student profile not found"]}, 404

    return _analytics_for_student(student.id, days)


def _analytics_for_student(student_id, days):
    cutoff = utc_now() - timedelta(days=days)
    logs = StudyLog.query.filter(
        StudyLog.student_id == student_id,
        StudyLog.end_time.isnot(None),
        StudyLog.start_time >= cutoff,
    ).order_by(StudyLog.start_time).all()

    daily = {}
    for log in logs:
        day = log.start_time.date().isoformat()
        daily[day] = daily.get(day, 0) + (log.duration_minutes or 0)

    series = [{"date": date, "minutes": minutes} for date, minutes in sorted(daily.items())]
    total_minutes = sum(daily.values())

    return {
        "series": series,
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 2),
    }, 200


def _analytics_for_institution(institution_id, days):
    cutoff = utc_now() - timedelta(days=days)
    students = Student.query.filter_by(institution_id=institution_id).all()
    student_ids = [s.id for s in students]

    logs = StudyLog.query.filter(
        StudyLog.student_id.in_(student_ids),
        StudyLog.end_time.isnot(None),
        StudyLog.start_time >= cutoff,
    ).all()

    daily = {}
    for log in logs:
        day = log.start_time.date().isoformat()
        daily[day] = daily.get(day, 0) + (log.duration_minutes or 0)

    series = [{"date": date, "minutes": minutes} for date, minutes in sorted(daily.items())]
    return {"series": series, "total_minutes": sum(daily.values())}, 200


def get_active_session(user):
    student = Student.query.filter_by(user_id=user.id).first()
    if not student:
        return {"errors": ["Student profile not found"]}, 404

    active = StudyLog.query.filter_by(student_id=student.id, end_time=None).first()
    return {"active_session": active.to_dict() if active else None}, 200
