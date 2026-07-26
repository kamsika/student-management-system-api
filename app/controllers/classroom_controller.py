from datetime import datetime as dt
import re

from app.extensions import db
from app.models import Classroom, Timetable, User

VALID_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def list_classrooms(user):
    query = Classroom.query

    if user.role == "teacher":
        query = query.filter_by(teacher_id=user.id, institution_id=user.institution_id)
    elif user.role == "institution_admin":
        query = query.filter_by(institution_id=user.institution_id)
    elif user.role == "super_admin":
        pass
    else:
        return {"errors": ["Access denied"]}, 403

    classrooms = query.order_by(Classroom.name).all()
    return {"classrooms": [c.to_dict() for c in classrooms]}, 200


def _parse_hhmm(value, field_name="time"):
    text = str(value or "").strip()
    if len(text) == 8 and text.count(":") == 2:
        text = text[:5]
    if not TIME_RE.match(text):
        return None, f"{field_name} must be HH:MM"
    return text, None


def _normalize_day(value):
    text = str(value or "").strip()
    for day in VALID_DAYS:
        if day.lower() == text.lower():
            return day
    return None


def _normalize_subject_teachers(raw, institution_id):
    if not isinstance(raw, list):
        return None, "subject_teachers must be a list"

    assignments = []
    seen_subjects = set()
    for item in raw:
        if not isinstance(item, dict):
            return None, "Each subject assignment must be an object"
        subject = str(item.get("subject") or item.get("subjectName") or "").strip()
        teacher_id = item.get("teacher_id", item.get("teacherId"))
        try:
            teacher_id = int(teacher_id)
        except (TypeError, ValueError):
            return None, f"Invalid teacher for subject '{subject or 'unknown'}'"
        if not subject:
            return None, "Subject name is required for each assignment"
        key = subject.lower()
        if key in seen_subjects:
            return None, f"Duplicate subject assignment: {subject}"
        teacher = User.query.filter_by(
            id=teacher_id,
            institution_id=institution_id,
            role="teacher",
        ).first()
        if not teacher:
            return None, f"Teacher not found for subject '{subject}'"
        seen_subjects.add(key)
        assignments.append({"subject": subject, "teacher_id": teacher_id})

    return assignments, None


def _normalize_timetable_slots(raw, assignments, institution_id):
    if not isinstance(raw, list):
        return None, "timetable must be a list"

    subject_to_teacher = {item["subject"].lower(): item["teacher_id"] for item in assignments}
    slots = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, f"Timetable slot {index + 1} is invalid"

        day = _normalize_day(item.get("dayOfWeek") or item.get("day_of_week"))
        subject = str(item.get("subjectName") or item.get("subject_name") or "").strip()
        start_raw = item.get("startTime") or item.get("start_time")
        end_raw = item.get("endTime") or item.get("end_time")
        teacher_id = item.get("teacherId", item.get("teacher_id"))

        if not day:
            return None, f"Timetable slot {index + 1}: day must be Monday–Sunday"
        if not subject:
            return None, f"Timetable slot {index + 1}: subject is required"

        start_time, start_error = _parse_hhmm(start_raw, "startTime")
        if start_error:
            return None, f"Timetable slot {index + 1}: {start_error}"
        end_time, end_error = _parse_hhmm(end_raw, "endTime")
        if end_error:
            return None, f"Timetable slot {index + 1}: {end_error}"

        start_mins = int(start_time[:2]) * 60 + int(start_time[3:])
        end_mins = int(end_time[:2]) * 60 + int(end_time[3:])
        if end_mins <= start_mins:
            return None, f"Timetable slot {index + 1}: endTime must be after startTime"

        subject_key = subject.lower()
        if subject_key not in subject_to_teacher:
            return None, f"Timetable subject '{subject}' is not in Subject & Teacher Assignment"

        if teacher_id is None or str(teacher_id).strip() == "":
            teacher_id = subject_to_teacher[subject_key]
        else:
            try:
                teacher_id = int(teacher_id)
            except (TypeError, ValueError):
                return None, f"Timetable slot {index + 1}: invalid teacher"

        teacher = User.query.filter_by(
            id=teacher_id,
            institution_id=institution_id,
            role="teacher",
        ).first()
        if not teacher:
            return None, f"Timetable slot {index + 1}: teacher not found"

        slots.append(
            {
                "day_of_week": day,
                "subject_name": subject,
                "start_time": start_time,
                "end_time": end_time,
                "teacher_id": teacher_id,
            }
        )

    return slots, None


def create_classroom(data, user):
    if user.role not in ("institution_admin", "super_admin"):
        return {"errors": ["Access denied"]}, 403
    if not user.institution_id and user.role != "super_admin":
        return {"errors": ["Institution required"]}, 400

    institution_id = user.institution_id
    name = (data.get("name") or "").strip()
    grade = (data.get("grade") or "").strip() or None

    # Legacy fields (still supported)
    schedule_start_time = data.get("schedule_start_time") or data.get("scheduleStartTime")
    teacher_id = data.get("teacher_id") or data.get("teacherId")

    subject_teachers_raw = data.get("subject_teachers")
    if subject_teachers_raw is None:
        subject_teachers_raw = data.get("subjectTeachers")

    timetable_raw = data.get("timetable")
    if timetable_raw is None:
        timetable_raw = data.get("timetable_slots") or data.get("timetableSlots")

    if not name:
        return {"errors": ["Classroom name is required"]}, 400

    # New complete flow: grade + assignments + timetable
    using_extended = (
        grade is not None
        or subject_teachers_raw is not None
        or timetable_raw is not None
    )

    assignments = []
    slots = []

    if using_extended:
        if not grade:
            return {"errors": ["Grade is required"]}, 400
        if subject_teachers_raw is None:
            return {"errors": ["Subject & Teacher Assignment is required"]}, 400
        if timetable_raw is None:
            return {"errors": ["Weekly timetable is required"]}, 400

        assignments, assign_error = _normalize_subject_teachers(subject_teachers_raw, institution_id)
        if assign_error:
            return {"errors": [assign_error]}, 400
        if not assignments:
            return {"errors": ["Add at least one subject with an assigned teacher"]}, 400

        slots, slot_error = _normalize_timetable_slots(timetable_raw, assignments, institution_id)
        if slot_error:
            return {"errors": [slot_error]}, 400
        if not slots:
            return {"errors": ["Add at least one timetable slot"]}, 400

        # Derive legacy required fields for compatibility with existing attendance flows.
        if not teacher_id:
            teacher_id = assignments[0]["teacher_id"]
        if not schedule_start_time:
            schedule_start_time = min(slot["start_time"] for slot in slots)
    else:
        # Legacy create: name + schedule_start_time + teacher_id
        if not schedule_start_time or not teacher_id:
            return {"errors": ["Name, schedule_start_time, and teacher_id are required"]}, 400

    try:
        teacher_id = int(teacher_id)
    except (TypeError, ValueError):
        return {"errors": ["teacher_id must be an integer"]}, 400

    teacher = User.query.filter_by(
        id=teacher_id,
        institution_id=institution_id,
        role="teacher",
    ).first()
    if not teacher:
        return {"errors": ["Teacher not found in institution"]}, 404

    try:
        time_text = str(schedule_start_time).strip()
        if len(time_text) == 8 and time_text.count(":") == 2:
            time_text = time_text[:5]
        parsed_time = (
            dt.strptime(time_text, "%H:%M").time()
            if len(time_text) == 5
            else dt.strptime(time_text, "%H:%M:%S").time()
        )

        classroom = Classroom(
            institution_id=institution_id,
            name=name,
            grade=grade,
            schedule_start_time=parsed_time,
            teacher_id=teacher_id,
            subject_teachers=assignments or None,
        )
        db.session.add(classroom)
        db.session.flush()

        for slot in slots:
            db.session.add(
                Timetable(
                    tenant_id=institution_id,
                    classroom_id=classroom.id,
                    student_id=None,
                    teacher_id=slot["teacher_id"],
                    day_of_week=slot["day_of_week"],
                    subject_name=slot["subject_name"],
                    start_time=slot["start_time"],
                    end_time=slot["end_time"],
                )
            )

        db.session.commit()
        return {"classroom": classroom.to_dict()}, 201
    except ValueError:
        db.session.rollback()
        return {"errors": ["Invalid schedule_start_time format. Use HH:MM"]}, 400
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to create classroom"]}, 500
