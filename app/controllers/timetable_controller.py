import re

from app.extensions import db
from app.models import Classroom, Student, Timetable
from app.utils.timetable_security import (
    assert_same_tenant,
    get_session_identity,
    tenant_scoped_timetable_query,
)

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


def _pick(data, *keys):
    for key in keys:
        if key in data and data[key] is not None and str(data[key]).strip() != "":
            return data[key]
    return None


def _parse_time(value, field_name):
    text = str(value).strip()
    if len(text) == 8 and text.count(":") == 2:
        text = text[:5]
    if not TIME_RE.match(text):
        return None, f"{field_name} must be HH:MM (24-hour)"
    return text, None


def _normalize_day(value):
    text = str(value or "").strip()
    for day in VALID_DAYS:
        if day.lower() == text.lower():
            return day
    return None


def _time_to_minutes(value):
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _resolve_classroom(classroom_id, identity):
    try:
        classroom_id = int(classroom_id)
    except (TypeError, ValueError):
        return None, {"errors": ["classroomId must be an integer"]}, 400

    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return None, {"errors": ["Classroom not found"]}, 404

    error, status = assert_same_tenant(classroom.institution_id, identity)
    if error:
        return None, error, status

    role = identity.get("role")
    user = identity.get("user")
    if role == "teacher" and user and classroom.teacher_id != user.id:
        return None, {"errors": ["Access denied"]}, 403
    if role == "student" and user:
        profile = user.student_profile
        if not profile or profile.institution_id != classroom.institution_id:
            return None, {"errors": ["Access denied"]}, 403
    if role == "parent" and user:
        children = Student.query.filter_by(parent_id=user.id).all()
        if not any(child.institution_id == classroom.institution_id for child in children):
            return None, {"errors": ["Access denied"]}, 403

    return classroom, None, None


def _resolve_student(student_id, identity, *, write=False):
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return None, {"errors": ["studentId must be an integer"]}, 400

    student = Student.query.get(student_id)
    if not student:
        return None, {"errors": ["Student not found"]}, 404

    error, status = assert_same_tenant(student.institution_id, identity)
    if error:
        return None, error, status

    role = identity.get("role")
    user = identity.get("user")
    if write and role not in ("institution_admin", "teacher", "super_admin"):
        return None, {"errors": ["Access denied"]}, 403
    if role == "student":
        if not user or not user.student_profile or user.student_profile.id != student.id:
            return None, {"errors": ["Access denied"]}, 403
    if role == "parent":
        if not user or student.parent_id != user.id:
            return None, {"errors": ["Access denied"]}, 403
    if role == "teacher" and user and student.institution_id != user.institution_id:
        return None, {"errors": ["Access denied"]}, 403

    return student, None, None


def list_timetable(classroom_id=None, student_id=None):
    identity = get_session_identity()
    query = tenant_scoped_timetable_query(Timetable.query, Timetable, identity)

    if classroom_id is not None and str(classroom_id).strip() != "":
        classroom, error, status = _resolve_classroom(classroom_id, identity)
        if error:
            return error, status
        query = query.filter_by(classroom_id=classroom.id)
    elif student_id is not None and str(student_id).strip() != "":
        student, error, status = _resolve_student(student_id, identity, write=False)
        if error:
            return error, status
        query = query.filter_by(student_id=student.id)
    else:
        role = identity.get("role")
        user = identity.get("user")
        if role == "student":
            if not user or not user.student_profile:
                return {"errors": ["Student profile not found"]}, 404
            query = query.filter_by(student_id=user.student_profile.id)
        elif role == "parent":
            child_ids = [
                s.id
                for s in Student.query.filter_by(
                    parent_id=user.id,
                    institution_id=identity["tenant_id"],
                ).all()
            ] if user else []
            if not child_ids:
                return {"timetable": [], "slots": [], "count": 0}, 200
            query = query.filter(Timetable.student_id.in_(child_ids))
        elif role == "teacher" and user:
            classroom_ids = [
                c.id
                for c in Classroom.query.filter_by(
                    teacher_id=user.id,
                    institution_id=identity["tenant_id"],
                ).all()
            ]
            if not classroom_ids:
                return {"timetable": [], "slots": [], "count": 0}, 200
            query = query.filter(Timetable.classroom_id.in_(classroom_ids))

    day_order = {day: index for index, day in enumerate(VALID_DAYS)}
    slots = query.all()
    slots.sort(
        key=lambda slot: (
            day_order.get(slot.day_of_week, 99),
            slot.start_time or "",
            slot.id,
        )
    )
    payload = [slot.to_dict() for slot in slots]
    return {
        "timetable": payload,
        "slots": payload,
        "count": len(payload),
        "tenantId": identity.get("tenant_id"),
    }, 200


def upsert_timetable(data):
    identity = get_session_identity()

    slot_id = _pick(data, "id")
    classroom_id = _pick(data, "classroomId", "classroom_id")
    student_id = _pick(data, "studentId", "student_id")
    day_of_week = _normalize_day(_pick(data, "dayOfWeek", "day_of_week"))
    subject_name = (_pick(data, "subjectName", "subject_name") or "").strip()
    start_raw = _pick(data, "startTime", "start_time")
    end_raw = _pick(data, "endTime", "end_time")

    if not day_of_week:
        return {"errors": [f"dayOfWeek must be one of: {', '.join(VALID_DAYS)}"]}, 400
    if not subject_name:
        return {"errors": ["subjectName is required"]}, 400
    if not start_raw or not end_raw:
        return {"errors": ["startTime and endTime are required"]}, 400

    start_time, start_error = _parse_time(start_raw, "startTime")
    if start_error:
        return {"errors": [start_error]}, 400
    end_time, end_error = _parse_time(end_raw, "endTime")
    if end_error:
        return {"errors": [end_error]}, 400
    if _time_to_minutes(end_time) <= _time_to_minutes(start_time):
        return {"errors": ["endTime must be after startTime"]}, 400

    if classroom_id is None and student_id is None and slot_id is None:
        return {"errors": ["classroomId or studentId is required"]}, 400

    slot = None
    if slot_id is not None:
        try:
            slot_id = int(slot_id)
        except (TypeError, ValueError):
            return {"errors": ["id must be an integer"]}, 400
        slot = Timetable.query.get(slot_id)
        if not slot:
            return {"errors": ["Timetable slot not found"]}, 404
        error, status = assert_same_tenant(slot.tenant_id, identity)
        if error:
            return error, status

    resolved_classroom_id = slot.classroom_id if slot else None
    resolved_student_id = slot.student_id if slot else None
    tenant_id = identity.get("tenant_id")

    if classroom_id is not None:
        classroom, error, status = _resolve_classroom(classroom_id, identity)
        if error:
            return error, status
        resolved_classroom_id = classroom.id
        tenant_id = classroom.institution_id
        if student_id is None and slot is None:
            resolved_student_id = None

    if student_id is not None:
        student, error, status = _resolve_student(student_id, identity, write=True)
        if error:
            return error, status
        resolved_student_id = student.id
        tenant_id = student.institution_id
        if classroom_id is None and slot is None:
            resolved_classroom_id = None

    if resolved_classroom_id is None and resolved_student_id is None:
        return {"errors": ["classroomId or studentId is required"]}, 400
    if identity.get("role") != "super_admin" and not tenant_id:
        return {"errors": ["Unable to resolve tenantId"]}, 400
    if slot and identity.get("role") != "super_admin":
        # Keep existing tenant; never allow cross-tenant reassignment.
        tenant_id = slot.tenant_id

    # For super_admin creating without an existing slot, tenant comes from classroom/student.
    if tenant_id is None:
        return {"errors": ["tenantId could not be resolved"]}, 400

    try:
        if slot is None:
            slot = Timetable(
                tenant_id=tenant_id,
                classroom_id=resolved_classroom_id,
                student_id=resolved_student_id,
                day_of_week=day_of_week,
                subject_name=subject_name,
                start_time=start_time,
                end_time=end_time,
            )
            db.session.add(slot)
            created = True
        else:
            if classroom_id is not None:
                slot.classroom_id = resolved_classroom_id
            if student_id is not None:
                slot.student_id = resolved_student_id
            if slot.classroom_id is None and slot.student_id is None:
                return {"errors": ["classroomId or studentId is required"]}, 400
            slot.day_of_week = day_of_week
            slot.subject_name = subject_name
            slot.start_time = start_time
            slot.end_time = end_time
            created = False

        db.session.commit()
        db.session.refresh(slot)
        return {
            "success": True,
            "message": "Timetable slot created" if created else "Timetable slot updated",
            "timetable": slot.to_dict(),
            "slot": slot.to_dict(),
        }, 201 if created else 200
    except Exception as exc:
        db.session.rollback()
        print(f"[TIMETABLE] upsert failed: {exc}")
        return {"errors": ["Failed to save timetable slot"]}, 500


def delete_timetable(slot_id):
    identity = get_session_identity()
    slot = Timetable.query.get(slot_id)
    if not slot:
        return {"errors": ["Timetable slot not found"]}, 404

    error, status = assert_same_tenant(slot.tenant_id, identity)
    if error:
        return error, status

    # Teachers may only delete slots in classrooms they teach (when classroom-scoped).
    user = identity.get("user")
    if identity.get("role") == "teacher" and slot.classroom_id and user:
        classroom = Classroom.query.get(slot.classroom_id)
        if not classroom or classroom.teacher_id != user.id:
            return {"errors": ["Access denied"]}, 403

    try:
        payload = slot.to_dict()
        db.session.delete(slot)
        db.session.commit()
        return {
            "success": True,
            "message": "Timetable slot deleted",
            "timetable": payload,
            "slot": payload,
        }, 200
    except Exception as exc:
        db.session.rollback()
        print(f"[TIMETABLE] delete failed: {exc}")
        return {"errors": ["Failed to delete timetable slot"]}, 500
