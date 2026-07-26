from calendar import monthrange
from collections import defaultdict
from datetime import timedelta

from app.models import Attendance, Classroom, Institution, Student, StudentPayment, Subject, User
from app.utils import parse_attendance_date, to_iso
from app.utils.csv_utils import export_teacher_attendance_history_csv
from app.utils.pdf_utils import generate_teacher_attendance_history_pdf

STATUS_INDICATORS = {
    "Present": "🟢",
    "Absent": "🔴",
    "Late": "🟡",
}

GRADE_TAB_LABELS = [f"Grade {n}" for n in range(5, 14)]


def _normalize_grade_key(value):
    text = (str(value) if value is not None else "").strip().lower()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return f"grade-{digits}"
    return text


def _grade_matches(student_grade, selected_grade):
    selected = (selected_grade or "").strip()
    if not selected or selected.lower() in ("all", "all grades"):
        return True
    return _normalize_grade_key(student_grade) == _normalize_grade_key(selected)


def _display_grade(student_grade):
    text = (student_grade or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits and _normalize_grade_key(text).startswith("grade-"):
        return f"Grade {digits}"
    return text


def _subject_catalog_names(institution_id):
    names = []
    seen = set()
    for subject in (
        Subject.query.filter_by(institution_id=institution_id).order_by(Subject.name.asc()).all()
    ):
        name = (subject.name or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _build_attendance_analytics(institution_id, attendance_date, students, attendance_rows):
    """Grade/subject percentages for the selected day + monthly present trend."""
    student_ids_set = {student.id for student in students}
    students_by_id = {student.id: student for student in students}
    students_by_grade = defaultdict(list)
    for student in students:
        grade_label = _display_grade(student.grade) or "Ungraded"
        students_by_grade[grade_label].append(student.id)

    present_by_student = set()
    present_by_grade = defaultdict(set)
    present_by_subject = defaultdict(set)
    for row in attendance_rows:
        if row.student_id not in student_ids_set:
            continue
        if row.status not in ("Present", "Late"):
            continue
        present_by_student.add(row.student_id)
        student = students_by_id.get(row.student_id)
        grade_label = _display_grade(student.grade) if student else "Ungraded"
        present_by_grade[grade_label or "Ungraded"].add(row.student_id)
        subject_name = (row.subject_name or "").strip() or "General"
        present_by_subject[subject_name].add(row.student_id)

    grade_wise = []
    for grade_label, student_ids in sorted(
        students_by_grade.items(),
        key=lambda item: (
            int("".join(ch for ch in item[0] if ch.isdigit()) or 999),
            item[0].lower(),
        ),
    ):
        total = len(student_ids)
        present = len(present_by_grade.get(grade_label, set()) & set(student_ids))
        percentage = round((present / total) * 100, 1) if total else 0.0
        grade_wise.append(
            {
                "grade": grade_label,
                "totalStudents": total,
                "presentCount": present,
                "percentage": percentage,
            }
        )

    # Subject-wise: use students enrolled in each subject when available.
    enrolled_by_subject = defaultdict(set)
    for student in students:
        for subject_name in student.get_enrolled_subjects():
            enrolled_by_subject[subject_name.strip()].add(student.id)

    subject_keys = sorted(
        set(enrolled_by_subject.keys()) | set(present_by_subject.keys()),
        key=lambda value: value.lower(),
    )
    subject_wise = []
    for subject_name in subject_keys:
        enrolled_ids = enrolled_by_subject.get(subject_name) or {
            student.id for student in students
        }
        total = len(enrolled_ids)
        present = len(present_by_subject.get(subject_name, set()) & enrolled_ids)
        percentage = round((present / total) * 100, 1) if total else 0.0
        subject_wise.append(
            {
                "subject": subject_name,
                "totalStudents": total,
                "presentCount": present,
                "percentage": percentage,
            }
        )

    month_start = attendance_date.replace(day=1)
    _, days_in_month = monthrange(attendance_date.year, attendance_date.month)
    month_end = attendance_date.replace(day=days_in_month)
    monthly_rows = (
        Attendance.query.join(Student, Attendance.student_id == Student.id)
        .filter(
            Student.institution_id == institution_id,
            Attendance.date >= month_start,
            Attendance.date <= month_end,
            Attendance.status.in_(("Present", "Late")),
        )
        .all()
    )
    present_by_day = defaultdict(set)
    for row in monthly_rows:
        present_by_day[row.date.isoformat()].add(row.student_id)

    monthly = []
    cursor = month_start
    while cursor <= month_end:
        key = cursor.isoformat()
        monthly.append(
            {
                "date": key,
                "label": cursor.strftime("%d %b"),
                "presentCount": len(present_by_day.get(key, set())),
                "recordCount": sum(
                    1 for row in monthly_rows if row.date == cursor
                ),
            }
        )
        cursor += timedelta(days=1)

    grades_attended = sorted(
        {
            _display_grade(student.grade) or "Ungraded"
            for student in students
            if student.id in present_by_student
        },
        key=lambda value: (
            int("".join(ch for ch in value if ch.isdigit()) or 999),
            value.lower(),
        ),
    )

    return {
        "gradeWise": grade_wise,
        "grade_wise": grade_wise,
        "subjectWise": subject_wise,
        "subject_wise": subject_wise,
        "monthly": monthly,
        "gradesAttended": grades_attended,
        "grades_attended": grades_attended,
        "gradesAttendedCount": len(grades_attended),
        "grades_attended_count": len(grades_attended),
    }


def get_teacher_attendance_overview(
    user,
    date_str=None,
    classroom_id=None,
    grade=None,
    subject=None,
    search=None,
):
    """Return attendance overview/history for the checker center."""
    if user.role != "teacher":
        return {"errors": ["Only teachers can access this overview"]}, 403
    if not user.institution_id:
        return {"errors": ["Teacher is not linked to a center"]}, 400

    attendance_date, date_error = parse_attendance_date(date_str)
    if date_error:
        return {"errors": [date_error]}, 400

    # Checker can view attendance for the whole center.
    classroom_query = Classroom.query.filter_by(institution_id=user.institution_id)

    resolved_classroom_id = None
    if classroom_id is not None and str(classroom_id).strip() != "":
        try:
            resolved_classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            return {"errors": ["classroomId must be an integer"]}, 400

        classroom = classroom_query.filter_by(id=resolved_classroom_id).first()
        if not classroom:
            return {"errors": ["Classroom not found"]}, 404
        classrooms = [classroom]
    else:
        classrooms = classroom_query.order_by(Classroom.name.asc(), Classroom.id.asc()).all()

    classroom_ids = [classroom.id for classroom in classrooms]
    classroom_by_id = {classroom.id: classroom for classroom in classrooms}

    selected_grade = (grade or "").strip() or "All"
    selected_subject = (subject or "").strip()
    if selected_subject.lower() in ("all", "all subjects"):
        selected_subject = ""
    search_text = (search or "").strip().lower()

    students_query = (
        Student.query.join(User, Student.user_id == User.id)
        .filter(
            Student.institution_id == user.institution_id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name.asc(), Student.registration_no.asc())
    )
    all_students = students_query.all()

    available_grades = sorted(
        {
            _display_grade(student.grade)
            for student in all_students
            if _display_grade(student.grade)
        },
        key=lambda value: (
            int("".join(ch for ch in value if ch.isdigit()) or 999),
            value.lower(),
        ),
    )
    # Prefer fixed Grade 5–13 tabs, then any extra grades from data.
    grade_tabs = list(GRADE_TAB_LABELS)
    for label in available_grades:
        if label not in grade_tabs:
            grade_tabs.append(label)

    students = [
        student for student in all_students if _grade_matches(student.grade, selected_grade)
    ]

    if search_text:
        students = [
            student
            for student in students
            if search_text in ((student.user.full_name if student.user else "") or "").lower()
            or search_text in (student.registration_no or "").lower()
        ]

    student_ids = [student.id for student in students]
    payment_period = attendance_date.strftime("%Y-%m")
    payments = (
        StudentPayment.query.filter(
            StudentPayment.student_id.in_(student_ids),
            StudentPayment.billing_period == payment_period,
        ).all()
        if student_ids
        else []
    )
    payment_by_student = {payment.student_id: payment for payment in payments}

    attendance_query = Attendance.query.filter(Attendance.date == attendance_date)
    if classroom_ids:
        attendance_query = attendance_query.filter(Attendance.classroom_id.in_(classroom_ids))
    else:
        attendance_query = attendance_query.join(Student, Attendance.student_id == Student.id).filter(
            Student.institution_id == user.institution_id
        )

    attendance_rows = attendance_query.order_by(
        Attendance.arrival_time.desc(),
        Attendance.id.desc(),
    ).all()

    # Subject filter options: center catalog + subjects marked today.
    catalog_subjects = _subject_catalog_names(user.institution_id)
    marked_subjects = {
        (row.subject_name or "").strip()
        for row in attendance_rows
        if (row.subject_name or "").strip()
    }
    subject_options = sorted(
        set(catalog_subjects) | marked_subjects,
        key=lambda value: value.lower(),
    )

    # Prefer Present/Late over Absent when aggregating per student for roster summary.
    attendance_by_student = {}
    status_rank = {"Present": 3, "Late": 2, "Absent": 1}
    for record in attendance_rows:
        current = attendance_by_student.get(record.student_id)
        if current is None or status_rank.get(record.status, 0) > status_rank.get(
            current.status, 0
        ):
            attendance_by_student[record.student_id] = record

    present_student_ids = set()
    late_student_ids = set()
    student_list = []

    for student in students:
        record = attendance_by_student.get(student.id)
        status = record.status if record else "Absent"
        if status not in STATUS_INDICATORS:
            status = "Absent"

        if status == "Present":
            present_student_ids.add(student.id)
        elif status == "Late":
            late_student_ids.add(student.id)
            present_student_ids.add(student.id)

        classroom = classroom_by_id.get(record.classroom_id) if record else None
        if classroom is None and len(classrooms) == 1:
            classroom = classrooms[0]

        student_list.append(
            {
                "studentId": student.id,
                "fullName": student.user.full_name if student.user else None,
                "registrationNo": student.registration_no,
                "grade": _display_grade(student.grade) or student.grade,
                "section": student.section,
                "status": status,
                "statusIndicator": STATUS_INDICATORS[status],
                "timestamp": to_iso(record.arrival_time) if record else None,
                "classroomId": classroom.id if classroom else None,
                "classroomName": classroom.name if classroom else None,
                "attendanceId": record.id if record else None,
                "subjectName": record.subject_name if record else None,
                "subject_name": record.subject_name if record else None,
                "subjectId": record.subject_id if record else None,
                "subject_id": record.subject_id if record else None,
                "monthlyPayment": (
                    payment_by_student[student.id].to_dict()
                    if student.id in payment_by_student
                    else {
                        "billing_period": payment_period,
                        "payment_status": "Pending",
                        "amount_due": None,
                        "paid_at": None,
                    }
                ),
                "monthlyPaymentStatus": payment_by_student[student.id].payment_status
                if student.id in payment_by_student
                else "Pending",
            }
        )

    students_by_id = {student.id: student for student in students}
    history_records = []

    for record in attendance_rows:
        student = students_by_id.get(record.student_id)
        if student is None:
            # Outside current grade/search filter.
            continue
        subject_name = (record.subject_name or "").strip()
        if selected_subject and subject_name.lower() != selected_subject.lower():
            continue
        if record.status not in ("Present", "Late", "Absent"):
            continue

        classroom = classroom_by_id.get(record.classroom_id)
        history_records.append(
            {
                "attendanceId": record.id,
                "studentId": student.id,
                "fullName": student.user.full_name if student.user else None,
                "registrationNo": student.registration_no,
                "grade": _display_grade(student.grade) or student.grade or "—",
                "subjectName": subject_name or "—",
                "subject_name": subject_name or None,
                "subjectId": record.subject_id,
                "subject_id": record.subject_id,
                "date": attendance_date.isoformat(),
                "timestamp": to_iso(record.arrival_time),
                "status": record.status,
                "statusIndicator": STATUS_INDICATORS.get(record.status, "🔴"),
                "classroomId": classroom.id if classroom else record.classroom_id,
                "classroomName": classroom.name if classroom else None,
                "markedVia": record.marked_via or None,
                "marked_via": record.marked_via or None,
                "attendanceMethod": Attendance.attendance_method_label(record.marked_via),
                "attendance_method": Attendance.attendance_method_label(record.marked_via),
                "markedBy": record.marked_by,
                "marked_by": record.marked_by,
            }
        )

    # When no subject filter, also show Absent roster rows for students with no Present/Late.
    if not selected_subject:
        marked_ids = {
            item["studentId"]
            for item in history_records
            if item["status"] in ("Present", "Late")
        }
        for student in students:
            if student.id in marked_ids:
                continue
            history_records.append(
                {
                    "attendanceId": None,
                    "studentId": student.id,
                    "fullName": student.user.full_name if student.user else None,
                    "registrationNo": student.registration_no,
                    "grade": _display_grade(student.grade) or student.grade or "—",
                    "subjectName": "—",
                    "subject_name": None,
                    "subjectId": None,
                    "subject_id": None,
                    "date": attendance_date.isoformat(),
                    "timestamp": None,
                    "status": "Absent",
                    "statusIndicator": STATUS_INDICATORS["Absent"],
                    "classroomId": None,
                    "classroomName": None,
                    "markedVia": None,
                    "marked_via": None,
                    "markedBy": None,
                    "marked_by": None,
                }
            )

    history_records.sort(
        key=lambda item: (
            0 if item["status"] in ("Present", "Late") else 1,
            (item["fullName"] or "").lower(),
            (item["subjectName"] or "").lower(),
        )
    )

    total_students = len(students)
    present_count = len(present_student_ids)
    late_count = len(late_student_ids)
    absent_count = max(total_students - present_count, 0)
    marked_record_count = sum(
        1 for item in history_records if item["status"] in ("Present", "Late")
    )

    # Analytics uses the unfiltered center roster for the selected date (still grade/search scoped).
    analytics = _build_attendance_analytics(
        user.institution_id,
        attendance_date,
        students,
        attendance_rows,
    )
    grades_attended_count = analytics.get("gradesAttendedCount", 0)

    return {
        "date": attendance_date.isoformat(),
        "classroomId": resolved_classroom_id,
        "classrooms": [classroom.to_dict() for classroom in classrooms],
        "selectedGrade": selected_grade if selected_grade else "All",
        "selected_grade": selected_grade if selected_grade else "All",
        "selectedSubject": selected_subject or "All",
        "selected_subject": selected_subject or "All",
        "grades": grade_tabs,
        "subjects": subject_options,
        "summary": {
            "totalStudents": total_students,
            "presentCount": present_count,
            "absentCount": absent_count,
            "lateCount": late_count,
            "totalRecords": marked_record_count,
            "gradesAttended": grades_attended_count,
            "grades_attended": grades_attended_count,
            "selectedGrade": selected_grade if selected_grade else "All",
        },
        "analytics": analytics,
        "students": student_list,
        "records": history_records,
    }, 200


def export_teacher_attendance_history(
    user,
    *,
    date_str=None,
    classroom_id=None,
    grade=None,
    subject=None,
    search=None,
    export_format="csv",
):
    """Export filtered attendance history rows as CSV or PDF."""
    result, status = get_teacher_attendance_overview(
        user,
        date_str=date_str,
        classroom_id=classroom_id,
        grade=grade,
        subject=subject,
        search=search,
    )
    if status != 200:
        return result, status

    records = result.get("records") or []
    export_rows = []
    for item in records:
        export_rows.append(
            {
                "student_name": item.get("fullName") or "",
                "registration_no": item.get("registrationNo") or "",
                "grade": item.get("grade") or "",
                "subject_name": item.get("subjectName") or item.get("subject_name") or "",
                "date": item.get("date") or result.get("date") or "",
                "arrival_time": item.get("timestamp") or "",
                "status": item.get("status") or "",
            }
        )

    institution = Institution.query.get(user.institution_id) if user.institution_id else None
    institution_name = institution.name if institution else "Tuition Center"
    selected_grade = result.get("selectedGrade") or "All"
    selected_subject = result.get("selectedSubject") or "All"
    date_label = result.get("date") or ""

    if export_format == "pdf":
        pdf_bytes = generate_teacher_attendance_history_pdf(
            institution_name=institution_name,
            date_label=date_label,
            grade_label=selected_grade,
            subject_label=selected_subject,
            records=export_rows,
        )
        return {
            "filename": f"attendance_history_{date_label}.pdf",
            "mimetype": "application/pdf",
            "content": pdf_bytes,
        }, 200

    csv_text = export_teacher_attendance_history_csv(export_rows)
    return {
        "filename": f"attendance_history_{date_label}.csv",
        "mimetype": "text/csv",
        "content": csv_text.encode("utf-8-sig"),
    }, 200
