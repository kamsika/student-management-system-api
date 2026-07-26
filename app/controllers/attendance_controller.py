from datetime import date

from app.extensions import db
from app.models import Attendance, Classroom, Student, StudentPayment, User
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


def _subject_enrollment_error(student, subject_names):
    """Return a warning when a student is not enrolled for an attendance subject."""
    enrolled_keys = {
        str(subject).strip().lower()
        for subject in student.get_enrolled_subjects()
        if str(subject).strip()
    }
    missing = []
    seen = set()
    for subject in subject_names:
        label = str(subject or "").strip()
        key = label.lower()
        if label and key not in enrolled_keys and key not in seen:
            seen.add(key)
            missing.append(label)
    if not missing:
        return None

    message = (
        f"Student is not enrolled for {', '.join(missing)}. "
        "Attendance stopped."
    )
    return {
        "success": False,
        "status": "NotEnrolled",
        "error_code": "STUDENT_NOT_ENROLLED",
        "not_enrolled": True,
        "unenrolledSubjects": missing,
        "unenrolled_subjects": missing,
        "warning": message,
        "errors": [message],
    }


def mark_attendance(data, user):
    raw_student_id = data.get("student_id")
    registration_no = (data.get("registration_no") or "").strip()
    classroom_id = data.get("classroom_id")
    status_override = data.get("status")
    prevent_duplicate = bool(data.get("prevent_duplicate"))
    subject_name = (data.get("subject_name") or data.get("subjectName") or "").strip()
    marked_via = (data.get("marked_via") or data.get("markedVia") or "").strip().lower()
    if marked_via and marked_via not in ("manual", "qr", "face"):
        marked_via = ""

    # Support both student_id (exact scanned QR text) and registration_no.
    scanned_id = ""
    if raw_student_id is not None and str(raw_student_id).strip():
        scanned_id = str(raw_student_id).strip()
    elif registration_no:
        scanned_id = registration_no

    print(
        f"[ATTENDANCE] Received attendance request for ID: {scanned_id!r} "
        f"(raw student_id={raw_student_id!r}, registration_no={registration_no!r}, "
        f"subject={subject_name!r})"
    )

    if not classroom_id:
        return {"errors": ["classroom_id is required"]}, 400

    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return {"errors": ["Classroom not found"]}, 404

    if user.role == "teacher":
        if classroom.teacher_id != user.id or classroom.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
    elif user.role == "institution_admin":
        if classroom.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
    else:
        return {"errors": ["Access denied"]}, 403

    if not scanned_id:
        return {"errors": ["student_id or registration_no is required"]}, 400

    student = _find_student_in_center(classroom.institution_id, scanned_id)
    if not student:
        return {"errors": [f"Student not found for ID: {scanned_id}"]}, 404

    # Subject-tagged requests must never create attendance for an un-enrolled
    # student. Timetable requests also validate the whole continuous chain
    # before reaching this function.
    if subject_name:
        enrollment_error = _subject_enrollment_error(student, [subject_name])
        if enrollment_error:
            return enrollment_error, 403

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
            subject_name=subject_name,
        ).first()

        if record and prevent_duplicate and record.status in ("Present", "Late"):
            payload = record.to_dict()
            subject_label = subject_name or "this class"
            print(
                f"[ATTENDANCE] Duplicate scan blocked student_id={student.id} "
                f"registration_no={student.registration_no!r} date={attendance_date.isoformat()} "
                f"subject={subject_name!r}"
            )
            return {
                "errors": [f"Already marked for {subject_label}."],
                "already_scanned": True,
                "alreadyMarkedFor": subject_label,
                "already_marked_for": subject_label,
                "attendance": payload,
            }, 409

        if record:
            record.status = status
            record.arrival_time = arrival_time if status != "Absent" else None
            record.marked_by = user.id
            record.subject_name = subject_name
            if marked_via:
                record.marked_via = marked_via
        else:
            record = Attendance(
                student_id=student.id,
                classroom_id=classroom.id,
                date=attendance_date,
                arrival_time=arrival_time if status != "Absent" else None,
                status=status,
                subject_name=subject_name,
                marked_via=marked_via,
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
            f"name={payload.get('student_name')!r} status={status} subject={subject_name!r}"
        )
        return {"attendance": payload, "delta_minutes": delta_minutes}, 200
    except Exception as exc:
        db.session.rollback()
        print(f"[ATTENDANCE] mark_attendance failed: {exc}")
        return {"errors": ["Failed to mark attendance"]}, 500


def create_attendance(data, user):
    """Kiosk/QR attendance: mark ONLY active timetable subjects for today."""
    from app.utils.timetable_auto_mark import resolve_auto_mark_subjects

    student_id = data.get("studentId")
    classroom_id = data.get("classroomId")
    timestamp = data.get("timestamp")
    selected_subjects_raw = data.get("selectedSubjects")
    if selected_subjects_raw is None:
        selected_subjects_raw = data.get("selected_subjects")
    marked_via = (data.get("markedVia") or data.get("marked_via") or "face").strip().lower()
    if marked_via not in ("face", "qr", "manual"):
        marked_via = "face"

    if student_id is None or str(student_id).strip() == "":
        return {"success": False, "errors": ["studentId is required"]}, 400
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return {"success": False, "errors": ["studentId must be an integer"]}, 400

    student = Student.query.get(student_id)
    if not student:
        return {"success": False, "errors": ["Student not found"]}, 404
    if student.institution_id != user.institution_id:
        return {"success": False, "errors": ["Access denied"]}, 403

    attendance_date = local_today()
    enrolled_subjects = student.get_enrolled_subjects()

    if classroom_id is not None and str(classroom_id).strip() != "":
        try:
            classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            return {"success": False, "errors": ["classroomId must be an integer"]}, 400
        classroom, error, error_status = _authorize_classroom(
            classroom_id, user, allow_super_admin=False
        )
        if error:
            return {"success": False, **error}, error_status
    else:
        classroom_query = Classroom.query.filter_by(institution_id=user.institution_id)
        if user.role == "teacher":
            classroom_query = classroom_query.filter_by(teacher_id=user.id)
        classrooms = classroom_query.order_by(Classroom.id.asc()).limit(2).all()
        if not classrooms:
            return {"success": False, "errors": ["No classroom is available"]}, 400
        if len(classrooms) > 1:
            return {
                "success": False,
                "errors": ["classroomId is required when more than one classroom is available"],
            }, 400
        classroom = classrooms[0]

    plan = resolve_auto_mark_subjects(
        student.id,
        classroom_id=classroom.id,
        enrolled_subjects=enrolled_subjects,
    )
    # Active timetable subjects only (already intersected with enrolled when set).
    subjects = list(plan.get("subjects") or [])
    eligible_slots = list(plan.get("eligibleSlots") or [])
    continuous_slots = list(plan.get("continuousSlots") or eligible_slots)

    # A first scan marks the current class automatically. If the caller is
    # confirming the consecutive-class prompt, only the checked subjects are
    # marked and the current class must remain selected.
    if isinstance(selected_subjects_raw, list):
        requested = []
        seen = set()
        for item in selected_subjects_raw:
            subject = str(item or "").strip()
            key = subject.lower()
            if subject and key not in seen:
                seen.add(key)
                requested.append(subject)

        markable_keys = {slot.subject_name.strip().lower() for slot in eligible_slots}
        current_slot = plan.get("currentSlot")
        current_key = current_slot.subject_name.strip().lower() if current_slot else None
        requested_keys = {value.lower() for value in requested}
        if current_key and current_key in markable_keys and current_key not in requested_keys:
            return {
                "success": False,
                "errors": ["The current class must remain selected."],
                "status": "SelectionRequired",
            }, 400
        invalid = [value for value in requested if value.lower() not in markable_keys]
        if invalid:
            return {
                "success": False,
                "errors": [f"Invalid timetable subject selection: {', '.join(invalid)}"],
            }, 400
        subjects = [
            slot.subject_name
            for slot in eligible_slots
            if slot.subject_name.strip().lower() in requested_keys
        ]

    # Upcoming continuous classes are checked by default in the confirmation
    # dialog; the user can untick them before the confirmation request.
    default_selected_keys = (
        {slot.subject_name.strip().lower() for slot in eligible_slots}
        if not isinstance(selected_subjects_raw, list)
        else {subject.lower() for subject in subjects}
    )

    payment_period = local_today().strftime("%Y-%m")
    payment = StudentPayment.query.filter_by(
        student_id=student.id,
        billing_period=payment_period,
    ).first()
    payment_payload = payment.to_dict() if payment else {
        "student_id": student.id,
        "billing_period": payment_period,
        "amount_due": None,
        "payment_status": "Pending",
        "paid_at": None,
    }

    today_timetable = [
        {
            "subjectName": slot.subject_name,
            "subject_name": slot.subject_name,
            "startTime": slot.start_time,
            "start_time": slot.start_time,
            "endTime": slot.end_time,
            "end_time": slot.end_time,
        }
        for slot in (plan.get("slots") or [])
    ]

    def _format_clock(value):
        text = str(value or "").strip()
        if len(text) >= 5:
            text = text[:5]
        try:
            hour_str, minute_str = text.split(":")
            hour, minute = int(hour_str), int(minute_str)
        except (TypeError, ValueError):
            return text or "--"
        suffix = "AM" if hour < 12 else "PM"
        hour12 = hour % 12 or 12
        return f"{hour12}:{minute:02d} {suffix}"

    def _slot_time_range(slot):
        return f"{_format_clock(slot.start_time)} - {_format_clock(slot.end_time)}"

    selected_keys = default_selected_keys
    current_slot = plan.get("currentSlot")
    current_key = current_slot.subject_name.strip().lower() if current_slot else None
    enrolled_keys = {subject.lower() for subject in enrolled_subjects}
    marked_option_rows = Attendance.query.filter_by(
        student_id=student.id,
        classroom_id=classroom.id,
        date=attendance_date,
    ).all()
    marked_by_subject = {
        (row.subject_name or "").strip().lower(): row
        for row in marked_option_rows
        if row.status in ("Present", "Late")
    }
    attendance_options = []
    for slot in continuous_slots:
        subject = slot.subject_name.strip()
        subject_key = subject.lower()
        is_enrolled = not enrolled_keys or subject_key in enrolled_keys
        is_current = subject_key == current_key
        attendance_options.append(
            {
                "slotId": slot.id,
                "slot_id": slot.id,
                "subjectName": subject,
                "subject_name": subject,
                "startTime": slot.start_time,
                "start_time": slot.start_time,
                "endTime": slot.end_time,
                "end_time": slot.end_time,
                "timeRange": _slot_time_range(slot),
                "isCurrent": is_current,
                "is_current": is_current,
                "isUpcoming": not is_current,
                "is_upcoming": not is_current,
                "isEnrolled": is_enrolled,
                "is_enrolled": is_enrolled,
                "selected": subject_key in selected_keys,
                "alreadyMarked": subject_key in marked_by_subject,
                "already_marked": subject_key in marked_by_subject,
                "disabled": not is_enrolled or is_current,
            }
        )

    def _scan_extras(
        *,
        marked=None,
        newly_marked=None,
        already_marked=None,
        present_details=None,
        already_details=None,
    ):
        marked_list = marked or []
        return {
            "studentId": student.id,
            "student_id": student.id,
            "studentName": student.user.full_name if student.user else None,
            "student_name": student.user.full_name if student.user else None,
            "registrationNo": student.registration_no,
            "registration_no": student.registration_no,
            "enrolledSubjects": enrolled_subjects,
            "enrolled_subjects": enrolled_subjects,
            "todayTimetable": today_timetable,
            "today_timetable": today_timetable,
            "markedAttendanceSubjects": marked_list,
            "marked_attendance_subjects": marked_list,
            "autoMarkedSubjects": marked_list,
            "newlyMarkedSubjects": newly_marked or [],
            "alreadyMarkedSubjects": already_marked or [],
            "presentNowDetails": present_details or [],
            "present_now_details": present_details or [],
            "alreadyMarkedDetails": already_details or [],
            "already_marked_details": already_details or [],
            "unenrolledSubjects": plan.get("unenrolledSubjects") or [],
            "unenrolled_subjects": plan.get("unenrolledSubjects") or [],
            "enrollmentWarning": plan.get("enrollmentWarning"),
            # Backward-compatible combined labels for older clients.
            "autoMarkedDetails": (present_details or []) + (already_details or []),
            "auto_marked_details": (present_details or []) + (already_details or []),
            "dayOfWeek": plan.get("dayOfWeek"),
            "currentTime": plan.get("currentTime"),
            "monthlyPayment": payment_payload,
            "monthly_payment": payment_payload,
            "paymentStatus": payment_payload["payment_status"],
            "payment_status": payment_payload["payment_status"],
            "attendanceOptions": attendance_options,
            "attendance_options": attendance_options,
            "attendanceSelectionRequired": len(attendance_options) > 1,
            "attendance_selection_required": len(attendance_options) > 1,
        }

    def _build_subject_details(subject_names, *, already=False):
        wanted = {name.lower() for name in (subject_names or [])}
        details = []
        for index, slot in enumerate(eligible_slots):
            if slot.subject_name.lower() not in wanted:
                continue
            time_range = _slot_time_range(slot)
            continuous = index > 0
            if already:
                label = f"Already marked for {slot.subject_name}."
            else:
                label = f"{slot.subject_name} ({time_range})"
                if continuous:
                    label = f"{slot.subject_name} ({time_range}) · Continuous Class"
            details.append(
                {
                    "subjectName": slot.subject_name,
                    "subject_name": slot.subject_name,
                    "status": "Present",
                    "alreadyMarked": already,
                    "already_marked": already,
                    "continuousClass": continuous,
                    "continuous_class": continuous,
                    "timeRange": time_range,
                    "time_range": time_range,
                    "startTime": slot.start_time,
                    "endTime": slot.end_time,
                    "label": label,
                }
            )
        if not details:
            for name in subject_names or []:
                label = f"Already marked for {name}." if already else f"{name} - Present"
                details.append(
                    {
                        "subjectName": name,
                        "subject_name": name,
                        "status": "Present",
                        "alreadyMarked": already,
                        "already_marked": already,
                        "continuousClass": False,
                        "continuous_class": False,
                        "timeRange": None,
                        "time_range": None,
                        "label": label,
                    }
                )
        return details

    if plan.get("blocked"):
        warning = plan.get("enrollmentWarning") or (
            "Student is not enrolled for the current continuous class. Attendance stopped."
        )
        return {
            "success": False,
            "status": "NotEnrolled",
            "error_code": "STUDENT_NOT_ENROLLED",
            "not_enrolled": True,
            "message": warning,
            "warning": warning,
            "errors": [warning],
            **_scan_extras(marked=[]),
        }, 403

    # No active timetable class right now → do NOT mark other enrolled subjects.
    if not subjects:
        return {
            "success": True,
            "status": "NoClass",
            "message": "No timetable class is scheduled for this student at the current time",
            "data": None,
            "attendance": None,
            **_scan_extras(marked=[]),
        }, 200

    created_records = []
    already_marked = []
    newly_marked = []

    for subject in subjects:
        result, result_status = mark_attendance(
            {
                "student_id": student.id,
                "classroom_id": classroom.id,
                "status": "Present",
                "scanned_at": timestamp,
                "date": attendance_date.isoformat(),
                "prevent_duplicate": True,
                "subject_name": subject,
                "marked_via": marked_via,
            },
            user,
        )
        if result_status == 409 and result.get("already_scanned"):
            already_marked.append(subject)
            created_records.append(result.get("attendance"))
            continue
        if result_status >= 400:
            return {
                "success": False,
                **result,
                "markedAttendanceSubjects": newly_marked,
                "autoMarkedSubjects": newly_marked,
                "enrolledSubjects": enrolled_subjects,
            }, result_status
        newly_marked.append(subject)
        created_records.append(result.get("attendance"))

    present_details = _build_subject_details(newly_marked, already=False)
    already_details = _build_subject_details(already_marked, already=True)
    # Subjects touched on this scan (new or confirmed already for active slot).
    marked = newly_marked + [name for name in already_marked if name not in newly_marked]

    if newly_marked and already_marked:
        message = (
            f"Marked Present for {', '.join(newly_marked)}. "
            + " ".join(f"Already marked for {name}." for name in already_marked)
        )
        response_status = "Present"
        http_status = 200
    elif newly_marked:
        message = f"Marked Present for: {', '.join(newly_marked)}"
        response_status = "Present"
        http_status = 201
    else:
        # Same active slot scanned again — per-subject warning, not full-day block.
        message = " ".join(f"Already marked for {name}." for name in already_marked) or (
            "Already marked for the current class."
        )
        response_status = "AlreadyMarked"
        http_status = 200

    primary = created_records[0] if created_records else None
    return {
        "success": True,
        "status": response_status,
        "message": message,
        "data": primary,
        "attendance": primary,
        "records": created_records,
        **_scan_extras(
            marked=marked,
            newly_marked=newly_marked,
            already_marked=already_marked,
            present_details=present_details,
            already_details=already_details,
        ),
    }, http_status


def save_manual_attendance(data, user):
    """Bulk upsert attendance for a classroom/subject/date (teacher/admin manual marking)."""
    from datetime import datetime, timezone

    from app.utils import get_app_tz

    classroom_id = data.get("classroomId") if data.get("classroomId") is not None else data.get("classroom_id")
    subject_name = (data.get("subjectName") or data.get("subject_name") or "").strip()
    date_raw = data.get("date")
    marking_time_raw = data.get("markingTime") or data.get("marking_time") or data.get("arrivalTime")
    entries = data.get("students") or data.get("entries") or []

    if classroom_id is None or str(classroom_id).strip() == "":
        return {"success": False, "errors": ["classroomId is required"]}, 400
    try:
        classroom_id = int(classroom_id)
    except (TypeError, ValueError):
        return {"success": False, "errors": ["classroomId must be an integer"]}, 400

    if not subject_name:
        return {"success": False, "errors": ["subjectName is required"]}, 400
    if not isinstance(entries, list) or len(entries) == 0:
        return {"success": False, "errors": ["students array is required"]}, 400

    classroom, error, status_code = _authorize_classroom(
        classroom_id, user, allow_super_admin=False
    )
    if error:
        return {"success": False, **error}, status_code

    attendance_date, date_error = parse_attendance_date(date_raw)
    if date_error:
        return {"success": False, "errors": [date_error]}, 400

    # Resolve optional marking time (HH:MM) in app timezone → stored UTC.
    arrival_time = utc_now()
    if marking_time_raw is not None and str(marking_time_raw).strip() != "":
        time_text = str(marking_time_raw).strip()
        if "T" in time_text or time_text.endswith("Z"):
            arrival_time = parse_incoming_timestamp(time_text)
        else:
            if len(time_text) == 8 and time_text.count(":") == 2:
                time_text = time_text[:5]
            try:
                hour_str, minute_str = time_text.split(":")
                hour, minute = int(hour_str), int(minute_str)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("out of range")
                local_dt = datetime(
                    attendance_date.year,
                    attendance_date.month,
                    attendance_date.day,
                    hour,
                    minute,
                    tzinfo=get_app_tz(),
                )
                arrival_time = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "errors": ["markingTime must be HH:MM"],
                }, 400

    saved = []
    errors = []

    try:
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"students[{index}] must be an object")
                continue

            raw_student_id = entry.get("studentId")
            if raw_student_id is None:
                raw_student_id = entry.get("student_id")
            status = (entry.get("status") or "").strip()

            if raw_student_id is None or str(raw_student_id).strip() == "":
                errors.append(f"students[{index}].studentId is required")
                continue
            try:
                student_id = int(raw_student_id)
            except (TypeError, ValueError):
                errors.append(f"students[{index}].studentId must be an integer")
                continue

            if status not in ("Present", "Absent", "Late"):
                errors.append(f"students[{index}].status must be Present, Absent, or Late")
                continue

            student = Student.query.get(student_id)
            if not student or student.institution_id != classroom.institution_id:
                errors.append(f"Student {student_id} not found in this center")
                continue

            enrollment_error = _subject_enrollment_error(student, [subject_name])
            if enrollment_error:
                errors.append(enrollment_error["errors"][0])
                continue

            record = Attendance.query.filter_by(
                student_id=student.id,
                classroom_id=classroom.id,
                date=attendance_date,
                subject_name=subject_name,
            ).first()

            mark_time = arrival_time if status != "Absent" else None

            if record:
                record.status = status
                record.arrival_time = mark_time
                record.marked_by = user.id
                record.marked_via = "manual"
            else:
                record = Attendance(
                    student_id=student.id,
                    classroom_id=classroom.id,
                    date=attendance_date,
                    arrival_time=mark_time,
                    status=status,
                    subject_name=subject_name,
                    marked_via="manual",
                    marked_by=user.id,
                )
                db.session.add(record)

            saved.append(record)

        if errors and not saved:
            db.session.rollback()
            return {"success": False, "errors": errors}, 400

        db.session.commit()
        for record in saved:
            db.session.refresh(record)

        return {
            "success": True,
            "message": f"Saved attendance for {len(saved)} student(s)",
            "classroomId": classroom.id,
            "subjectName": subject_name,
            "date": attendance_date.isoformat(),
            "markingTime": marking_time_raw,
            "markedVia": "manual",
            "count": len(saved),
            "records": [record.to_dict() for record in saved],
            "errors": errors or None,
        }, 200
    except Exception as exc:
        db.session.rollback()
        print(f"[ATTENDANCE] save_manual_attendance failed: {exc}")
        return {"success": False, "errors": ["Failed to save manual attendance"]}, 500


def get_manual_attendance_roster(user, classroom_id=None, subject_name=None, date_str=None):
    """Roster + current status for manual marking (filtered by subject when provided)."""
    if classroom_id is None or str(classroom_id).strip() == "":
        return {"errors": ["classroomId is required"]}, 400
    try:
        classroom_id = int(classroom_id)
    except (TypeError, ValueError):
        return {"errors": ["classroomId must be an integer"]}, 400

    subject_name = (subject_name or "").strip()
    classroom, error, status_code = _authorize_classroom(
        classroom_id, user, allow_super_admin=False
    )
    if error:
        return error, status_code

    attendance_date, date_error = parse_attendance_date(date_str)
    if date_error:
        return {"errors": [date_error]}, 400

    students = (
        Student.query.join(User, Student.user_id == User.id)
        .filter(
            Student.institution_id == classroom.institution_id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name.asc(), Student.registration_no.asc())
        .all()
    )

    query = Attendance.query.filter_by(classroom_id=classroom.id, date=attendance_date)
    if subject_name:
        query = query.filter_by(subject_name=subject_name)
    attendance_rows = query.all()

    attendance_map = {}
    for record in attendance_rows:
        if subject_name:
            attendance_map[record.student_id] = record
            continue
        current = attendance_map.get(record.student_id)
        if current is None:
            attendance_map[record.student_id] = record
            continue
        rank = {"Present": 3, "Late": 2, "Absent": 1}
        if rank.get(record.status, 0) > rank.get(current.status, 0):
            attendance_map[record.student_id] = record

    # Distinct subjects available for this classroom from timetable + existing marks.
    from app.models import Timetable

    subject_set = set()
    for slot in Timetable.query.filter_by(classroom_id=classroom.id).all():
        if slot.subject_name:
            subject_set.add(slot.subject_name)
    for record in Attendance.query.filter(
        Attendance.classroom_id == classroom.id,
        Attendance.subject_name != "",
    ).all():
        subject_set.add(record.subject_name)

    roster = []
    for student in students:
        record = attendance_map.get(student.id)
        roster.append(
            {
                "studentId": student.id,
                "fullName": student.user.full_name if student.user else None,
                "registrationNo": student.registration_no,
                "status": record.status if record else None,
                "statusIndicator": {
                    "Present": "🟢",
                    "Absent": "🔴",
                    "Late": "🟡",
                }.get(record.status if record else "", ""),
                "markedVia": record.marked_via if record else None,
                "arrivalTime": record.to_dict().get("arrival_time") if record else None,
                "attendance": record.to_dict() if record else None,
            }
        )

    return {
        "classroom": classroom.to_dict(),
        "subjectName": subject_name or None,
        "date": attendance_date.isoformat(),
        "subjects": sorted(subject_set),
        "students": roster,
        "count": len(roster),
    }, 200


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

    # Reuse kiosk timetable auto-marking for QR scans as well.
    return create_attendance(
        {
            "studentId": student.id,
            "classroomId": classroom.id,
            "timestamp": data.get("scanned_at"),
            "status": "Present",
            "markedVia": "qr",
            "selected_subjects": data.get("selected_subjects")
            if data.get("selected_subjects") is not None
            else data.get("selectedSubjects"),
        },
        user,
    )


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
    attendance_rows = Attendance.query.filter_by(classroom_id=classroom_id, date=attendance_date).all()
    attendance_map = {}
    for record in attendance_rows:
        current = attendance_map.get(record.student_id)
        if current is None:
            attendance_map[record.student_id] = record
            continue
        # Prefer Present/Late over Absent when multiple subject rows exist.
        rank = {"Present": 3, "Late": 2, "Absent": 1}
        if rank.get(record.status, 0) > rank.get(current.status, 0):
            attendance_map[record.student_id] = record

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
