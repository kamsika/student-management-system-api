from sqlalchemy import func, or_
import re

from app.extensions import db
from app.models import (
    Attendance,
    Classroom,
    Institution,
    Student,
    StudentPayment,
    Subject,
    Timetable,
    User,
)
from app.models.student_model import normalize_enrolled_subjects
from app.utils.csv_utils import parse_students_csv, generate_students_template_csv
from app.utils.student_id_utils import build_placeholder_emails, generate_next_registration_no
from app.controllers.payment_controller import _enrich_payment_dict, get_or_build_current_payment_payload
from app.models.student_payment_model import (
    billing_period_from_month_year,
    month_year_from_billing_period,
)
from app.utils import local_today, utc_now


def _normalize_name(name: str) -> str:
    return (name or "").strip().lower()


def _normalize_contact(contact: str) -> str:
    return (contact or "").replace(" ", "").strip()


def _grade_sort_key(grade: str):
    match = re.search(r"(\d+)", grade)
    if match:
        return (0, int(match.group(1)), grade.lower())
    return (1, 0, grade.lower())


def _resolve_student_classroom(student, user=None):
    """Best-effort classroom for display (teacher class, timetable, or center default)."""
    if user is not None and user.role == "teacher" and user.institution_id:
        classroom = (
            Classroom.query.filter_by(institution_id=user.institution_id)
            .order_by(Classroom.name.asc())
            .first()
        )
        if classroom:
            return classroom

    slot = (
        Timetable.query.filter(Timetable.student_id == student.id, Timetable.classroom_id.isnot(None))
        .order_by(Timetable.id.desc())
        .first()
    )
    if slot and slot.classroom_id:
        classroom = Classroom.query.get(slot.classroom_id)
        if classroom:
            return classroom

    return (
        Classroom.query.filter_by(institution_id=student.institution_id)
        .order_by(Classroom.name.asc())
        .first()
    )


def _enrolled_subject_payloads(student):
    """Map student enrolled subject names to Subject rows for the same center."""
    names = student.get_enrolled_subjects()
    if not names:
        return [], []

    catalog = Subject.query.filter_by(institution_id=student.institution_id).all()
    by_name = {item.name.strip().lower(): item for item in catalog if item.name}

    details = []
    for name in names:
        match = by_name.get(name.strip().lower())
        details.append(
            {
                "id": match.id if match else None,
                "name": name,
                "code": match.code if match else None,
                "teacher_id": match.teacher_id if match else None,
                "teacherId": match.teacher_id if match else None,
                "teacher_name": match.teacher.full_name if match and match.teacher else None,
                "teacherName": match.teacher.full_name if match and match.teacher else None,
            }
        )
    return names, details


def _already_marked_subjects_today(student):
    today = local_today()
    rows = (
        Attendance.query.filter_by(student_id=student.id, date=today)
        .filter(Attendance.status.in_(("Present", "Late")))
        .all()
    )
    details = []
    names = []
    seen = set()
    for row in rows:
        name = (row.subject_name or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        details.append(
            {
                "id": row.subject_id,
                "subject_id": row.subject_id,
                "subjectId": row.subject_id,
                "name": name,
                "subject_name": name,
                "subjectName": name,
            }
        )
    return names, details


def _student_detail_dict(student, user=None):
    payload = student.to_dict()
    enrolled_names, enrolled_details = _enrolled_subject_payloads(student)
    payload["enrolled_subjects"] = enrolled_names
    payload["enrolledSubjects"] = enrolled_names
    payload["registered_subjects"] = enrolled_details
    payload["registeredSubjects"] = enrolled_details

    already_names, already_details = _already_marked_subjects_today(student)
    payload["already_marked_subjects"] = already_names
    payload["alreadyMarkedSubjects"] = already_names
    payload["already_marked_subject_details"] = already_details
    payload["alreadyMarkedSubjectDetails"] = already_details

    institution = student.institution or Institution.query.get(student.institution_id)
    institution_name = institution.name if institution else None
    payload["institution_id"] = student.institution_id
    payload["institutionId"] = student.institution_id
    payload["institution_name"] = institution_name
    payload["institutionName"] = institution_name
    payload["tuition_center_name"] = institution_name
    payload["tuitionCenterName"] = institution_name
    # No profile photo column yet — keep null so UI can fall back to initials.
    payload["profile_photo"] = None
    payload["profilePhoto"] = None
    payload["photo_url"] = None
    payload["photoUrl"] = None

    classroom = _resolve_student_classroom(student, user=user)
    payload["classroom_id"] = classroom.id if classroom else None
    payload["classroomId"] = classroom.id if classroom else None
    payload["classroom_name"] = classroom.name if classroom else None
    payload["classroomName"] = classroom.name if classroom else None
    if classroom:
        payload["classroom"] = {
            "id": classroom.id,
            "name": classroom.name,
            "grade": classroom.grade,
        }
        if not payload.get("grade") and classroom.grade:
            payload["grade"] = classroom.grade
    else:
        payload["classroom"] = None

    payment_payload, _payment = get_or_build_current_payment_payload(student.id)
    payload["monthlyPayment"] = payment_payload
    payload["monthly_payment"] = payment_payload
    payload["currentMonthFee"] = payment_payload
    payload["current_month_fee"] = payment_payload
    payload["paymentStatus"] = payment_payload.get("payment_status")
    payload["payment_status"] = payment_payload.get("payment_status")

    from app.models import FaceData

    face_row = FaceData.query.filter_by(student_id=student.id).first()
    payload["has_face_descriptor"] = bool(
        (face_row and face_row.face_embedding) or student.face_descriptor
    )
    return payload


def _find_student_by_scanned_id(institution_id, scanned_id):
    """Resolve QR / lookup value to a student in the center."""
    scanned = (str(scanned_id) if scanned_id is not None else "").strip()
    if not scanned or not institution_id:
        return None

    student = Student.query.filter_by(
        institution_id=institution_id,
        registration_no=scanned,
    ).first()
    if student:
        return student

    if scanned.isdigit():
        student = Student.query.filter_by(
            institution_id=institution_id,
            id=int(scanned),
        ).first()
        if student:
            return student

    return None


def _authorize_student_access(student, user):
    if not student:
        return {"errors": ["Student not found"]}, 404
    if user.role == "super_admin":
        return None
    if user.role in ("institution_admin", "teacher"):
        if student.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
        return None
    return {"errors": ["Access denied"]}, 403


def get_student(student_id, user):
    """Return one student with enrolled/registered subjects and center details."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student_access(student, user)
    if denied:
        return denied

    return {"student": _student_detail_dict(student, user=user)}, 200


def lookup_student(scanned_id, user):
    """Lookup student by QR registration no / numeric id for checker preview."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    scanned = (str(scanned_id) if scanned_id is not None else "").strip()
    if not scanned:
        return {"errors": ["Invalid QR code"], "invalid_qr": True}, 400

    if user.role == "super_admin":
        student = Student.query.filter_by(registration_no=scanned).first()
        if not student and scanned.isdigit():
            student = Student.query.get(int(scanned))
    else:
        if not user.institution_id:
            return {"errors": ["User is not linked to a center"]}, 400
        student = _find_student_by_scanned_id(user.institution_id, scanned)

    if not student:
        return {
            "errors": [f"Invalid QR code. Student not found: {scanned}"],
            "invalid_qr": True,
        }, 404

    denied = _authorize_student_access(student, user)
    if denied:
        return denied

    payload = _student_detail_dict(student, user=user)
    return {
        "success": True,
        "student": payload,
        "scanned_id": scanned,
        "scannedId": scanned,
    }, 200


def _find_duplicate_student(institution_id, full_name, contact):
    students = Student.query.filter_by(institution_id=institution_id).all()
    target_name = _normalize_name(full_name)
    target_contact = _normalize_contact(contact)

    for student in students:
        if not student.user:
            continue
        if _normalize_name(student.user.full_name) != target_name:
            continue
        if _normalize_contact(student.user.phone_number) == target_contact:
            return student
    return None


def _resolve_teacher_admission_classroom(data, user, grade):
    from app.controllers.teacher_controller import (
        _normalize_grade_key,
        _teacher_assigned_classroom_ids,
    )

    assigned_classrooms = _teacher_assigned_classroom_ids(user)
    raw_classroom_id = next(
        (
            data.get(key)
            for key in (
                "classroom_id",
                "classroomId",
                "class_id",
                "classId",
                "grade_id",
                "gradeId",
            )
            if data.get(key) is not None
        ),
        None,
    )
    if raw_classroom_id is not None and str(raw_classroom_id).strip():
        try:
            classroom_id = int(raw_classroom_id)
        except (TypeError, ValueError):
            return None, {"errors": ["classroom_id must be an integer"]}, 400
        classroom = next(
            (item for item in assigned_classrooms if item.id == classroom_id),
            None,
        )
    else:
        requested_grade = _normalize_grade_key(grade)
        classroom = next(
            (
                item
                for item in assigned_classrooms
                if requested_grade
                and _normalize_grade_key(item.grade) == requested_grade
            ),
            None,
        )

    if not classroom:
        return (
            None,
            {"errors": ["Access denied — class is not assigned to this teacher"]},
            403,
        )
    return classroom, None, None


def list_students(user, search=None, grade=None):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    query = Student.query.join(User, Student.user_id == User.id)
    if user.role != "super_admin":
        query = query.filter(Student.institution_id == user.institution_id)

    # Distinct grades for filter dropdown (institution-scoped, not limited by search/grade).
    grades_query = db.session.query(Student.grade).filter(Student.grade.isnot(None))
    if user.role != "super_admin":
        grades_query = grades_query.filter(Student.institution_id == user.institution_id)
    available_grades = sorted(
        {
            str(value).strip()
            for (value,) in grades_query.distinct().all()
            if value and str(value).strip()
        },
        key=_grade_sort_key,
    )

    search_text = (search or "").strip()
    if search_text:
        pattern = f"%{search_text.lower()}%"
        query = query.filter(
            or_(
                func.lower(User.full_name).like(pattern),
                func.lower(Student.registration_no).like(pattern),
                func.lower(User.email).like(pattern),
            )
        )

    grade_filter = (grade or "").strip()
    if grade_filter and grade_filter.lower() not in ("all", "all grades"):
        if grade_filter.lower() == "ungraded":
            query = query.filter(or_(Student.grade.is_(None), Student.grade == ""))
        else:
            query = query.filter(func.lower(Student.grade) == grade_filter.lower())

    students = query.order_by(
        Student.grade.asc(),
        User.full_name.asc(),
        Student.registration_no.asc(),
    ).all()
    return {
        "students": [_student_detail_dict(student, user=user) for student in students],
        "count": len(students),
        "search": search_text or None,
        "grade": grade_filter or None,
        "grades": available_grades,
    }, 200


def update_student_subjects(student_id, data, user):
    """Replace enrolled subjects for a student (teachers/admins)."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student_access(student, user)
    if denied:
        return denied

    raw = (
        data.get("enrolledSubjects")
        if data.get("enrolledSubjects") is not None
        else data.get("enrolled_subjects")
        if data.get("enrolled_subjects") is not None
        else data.get("subjects")
    )
    if raw is None:
        return {"errors": ["enrolledSubjects is required"]}, 400

    subjects = normalize_enrolled_subjects(raw)

    try:
        student.enrolled_subjects = subjects
        db.session.commit()
        db.session.refresh(student)
        payload = _student_detail_dict(student, user=user)
        return {
            "success": True,
            "student": payload,
            "enrolledSubjects": subjects,
            "enrolled_subjects": subjects,
            "message": "Enrolled subjects updated successfully",
        }, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to update enrolled subjects"]}, 500


def update_student_payment_status(student_id, data, user):
    """Create or update the student's monthly fee status."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student_access(student, user)
    if denied:
        return denied

    period = str(data.get("billingPeriod") or data.get("billing_period") or local_today().strftime("%Y-%m")).strip()
    status = str(data.get("paymentStatus") or data.get("payment_status") or "").strip().title()
    if len(period) != 7 or period[4] != "-":
        return {"errors": ["billingPeriod must be YYYY-MM"]}, 400
    if status not in ("Pending", "Paid", "Overdue"):
        return {"errors": ["paymentStatus must be Pending, Paid, or Overdue"]}, 400

    month, year = month_year_from_billing_period(period)
    amount = data.get("amount")
    if amount is None:
        amount = data.get("amount_due")
    try:
        amount_value = float(amount) if amount is not None and str(amount).strip() != "" else None
    except (TypeError, ValueError):
        return {"errors": ["amount must be a number"]}, 400

    payment = StudentPayment.query.filter_by(
        student_id=student.id,
        billing_period=period,
    ).first()
    if payment is None:
        payment = StudentPayment(
            student_id=student.id,
            billing_period=period or billing_period_from_month_year(month or local_today().month, year or local_today().year),
            month=month,
            year=year,
            amount=amount_value,
            amount_due=amount_value,
            payment_status=status,
            payment_date=local_today() if status == "Paid" else None,
            paid_at=utc_now() if status == "Paid" else None,
            collected_by=user.id if status == "Paid" and user.role == "teacher" else None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        payment.sync_period_fields()
        db.session.add(payment)
    else:
        payment.payment_status = status
        if amount_value is not None:
            payment.amount = amount_value
            payment.amount_due = amount_value
        if month and year:
            payment.month = month
            payment.year = year
            payment.billing_period = period
        payment.payment_date = local_today() if status == "Paid" else None
        payment.paid_at = utc_now() if status == "Paid" else None
        if status == "Paid" and user.role == "teacher":
            payment.collected_by = user.id
        elif status != "Paid":
            payment.collected_by = None
        payment.sync_period_fields()

    try:
        db.session.commit()
        db.session.refresh(payment)
        return {"success": True, "payment": _enrich_payment_dict(payment) if payment.id else payment.to_dict()}, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to update payment status"]}, 500


def import_students(file_content, user, default_password="Student@123"):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403

    try:
        rows = parse_students_csv(file_content)
    except ValueError as exc:
        return {"errors": [str(exc)]}, 400

    created = []
    errors = []

    for row in rows:
        reg_no = row["registration_no"]
        if Student.query.filter_by(institution_id=user.institution_id, registration_no=reg_no).first():
            errors.append(f"Duplicate registration: {reg_no}")
            continue

        parent_email = row["parent_email"].lower()
        parent = User.query.filter_by(email=parent_email).first()
        if not parent:
            parent = User(
                institution_id=user.institution_id,
                email=parent_email,
                role="parent",
                full_name=row["parent_name"],
                phone_number=row["parent_phone"],
                is_active=True,
            )
            parent.set_password(default_password)
            db.session.add(parent)
            db.session.flush()
        elif parent.role != "parent":
            errors.append(f"Email {parent_email} belongs to non-parent user")
            continue

        student_email = row["email"].lower()
        if User.query.filter_by(email=student_email).first():
            errors.append(f"Student email already exists: {student_email}")
            continue

        student_user = User(
            institution_id=user.institution_id,
            email=student_email,
            role="student",
            full_name=row["full_name"],
            phone_number=row.get("contact") or row.get("phone") or None,
            is_active=True,
        )
        student_user.set_password(default_password)
        db.session.add(student_user)
        db.session.flush()

        student = Student(
            institution_id=user.institution_id,
            user_id=student_user.id,
            parent_id=parent.id,
            registration_no=reg_no,
            grade=row.get("grade") or None,
            section=row.get("section") or None,
            gender=row.get("gender") or None,
        )
        db.session.add(student)
        created.append(reg_no)

    try:
        db.session.commit()
        return {"created": created, "errors": errors, "count": len(created)}, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to import students"]}, 500


def get_import_template():
    return generate_students_template_csv()


def get_parent_children(user):
    if user.role != "parent":
        return {"errors": ["Access denied"]}, 403

    students = Student.query.filter_by(parent_id=user.id).all()
    return {"students": [s.to_dict() for s in students]}, 200


def list_teachers(user):
    if user.role not in ("institution_admin", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    query = User.query.filter_by(role="teacher")
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)

    teachers = query.all()
    return {"teachers": [t.to_dict() for t in teachers]}, 200


def create_student(data, user, default_password="Student@123"):
    if user.role not in ("institution_admin", "teacher"):
        return {"errors": ["Access denied"]}, 403

    full_name = (data.get("full_name") or data.get("name") or "").strip()
    grade = (data.get("grade") or "").strip() or None
    section = (data.get("section") or "").strip() or None
    gender = (data.get("gender") or "").strip() or None
    contact = (data.get("contact") or data.get("contact_number") or "").strip() or None
    enrolled_subjects = normalize_enrolled_subjects(
        data.get("enrolledSubjects")
        if data.get("enrolledSubjects") is not None
        else data.get("enrolled_subjects")
    )

    if user.role == "teacher":
        selected_classroom, error, status = _resolve_teacher_admission_classroom(
            data, user, grade
        )
        if error:
            return error, status
        grade = (
            selected_classroom.grade or selected_classroom.name or ""
        ).strip() or grade

    if not full_name:
        return {"errors": ["Name is required"]}, 400

    if gender and gender not in ("Male", "Female", "Other"):
        return {"errors": ["Gender must be Male, Female, or Other"]}, 400

    duplicate = _find_duplicate_student(user.institution_id, full_name, contact or "")
    if duplicate:
        return {"errors": ["Student already exists!"]}, 409

    institution = Institution.query.get(user.institution_id)
    subdomain = institution.subdomain if institution else "school"
    registration_no = generate_next_registration_no(user.institution_id)
    student_email, parent_email = build_placeholder_emails(registration_no, subdomain)

    suffix = 1
    while User.query.filter_by(email=student_email).first():
        student_email = student_email.replace("@", f"+{suffix}@", 1)
        suffix += 1

    suffix = 1
    while User.query.filter_by(email=parent_email).first():
        parent_email = parent_email.replace("@", f"+{suffix}@", 1)
        suffix += 1

    try:
        parent = User(
            institution_id=user.institution_id,
            email=parent_email,
            role="parent",
            full_name=f"Guardian of {full_name}",
            phone_number=contact,
            is_active=True,
        )
        parent.set_password(default_password)
        db.session.add(parent)
        db.session.flush()

        student_user = User(
            institution_id=user.institution_id,
            email=student_email,
            role="student",
            full_name=full_name,
            phone_number=contact,
            is_active=True,
        )
        student_user.set_password(default_password)
        db.session.add(student_user)
        db.session.flush()

        student = Student(
            institution_id=user.institution_id,
            user_id=student_user.id,
            parent_id=parent.id,
            registration_no=registration_no,
            grade=grade,
            section=section,
            gender=gender,
            enrolled_subjects=enrolled_subjects,
        )
        db.session.add(student)
        db.session.commit()

        return {
            "student": student.to_dict(),
            "message": f"Student {registration_no} created successfully",
        }, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to create student"]}, 500


def update_student(student_id, data, user):
    """Update student profile fields including enrolledSubjects."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student_access(student, user)
    if denied:
        return denied

    if user.role == "teacher" and student.institution_id != user.institution_id:
        return {"errors": ["Access denied"]}, 403

    try:
        if "full_name" in data or "name" in data:
            full_name = (data.get("full_name") or data.get("name") or "").strip()
            if not full_name:
                return {"errors": ["Name is required"]}, 400
            if student.user:
                student.user.full_name = full_name

        if "grade" in data:
            student.grade = (data.get("grade") or "").strip() or None
        if "section" in data:
            student.section = (data.get("section") or "").strip() or None
        if "gender" in data:
            gender = (data.get("gender") or "").strip() or None
            if gender and gender not in ("Male", "Female", "Other"):
                return {"errors": ["Gender must be Male, Female, or Other"]}, 400
            student.gender = gender
        if "contact" in data or "contact_number" in data:
            contact = (data.get("contact") or data.get("contact_number") or "").strip() or None
            if student.user:
                student.user.phone_number = contact

        if "enrolledSubjects" in data or "enrolled_subjects" in data:
            raw = (
                data.get("enrolledSubjects")
                if "enrolledSubjects" in data
                else data.get("enrolled_subjects")
            )
            student.enrolled_subjects = normalize_enrolled_subjects(raw)

        db.session.commit()
        db.session.refresh(student)
        return {
            "student": student.to_dict(),
            "message": "Student updated successfully",
        }, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to update student"]}, 500


def list_face_profiles(user):
    """Return students with optional descriptors for recognition matching."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    query = Student.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)

    students = query.order_by(Student.id.asc()).all()
    profiles = []
    for student in students:
        from app.models import FaceData

        row = FaceData.query.filter_by(student_id=student.id).first()
        embedding = row.face_embedding if row else student.face_descriptor
        payload = student.to_dict(include_face_descriptor=False)
        profiles.append(
            {
                "id": payload["id"],
                "registration_no": payload["registration_no"],
                "full_name": payload["full_name"],
                "grade": payload.get("grade"),
                "enrolled_subjects": payload.get("enrolled_subjects") or [],
                "enrolledSubjects": payload.get("enrolledSubjects") or payload.get("enrolled_subjects") or [],
                "descriptor": embedding,
                "has_face_descriptor": bool(embedding),
            }
        )
    return {"profiles": profiles}, 200


def save_student_face(student_id, data, user):
    """Persist a 128-element face-api.js descriptor for a student."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student_access(student, user)
    if denied:
        return denied

    descriptor = data.get("descriptor")
    if not isinstance(descriptor, list):
        return {"errors": ["descriptor must be an array of numbers"]}, 400
    if len(descriptor) != 128:
        return {"errors": ["descriptor must contain exactly 128 numbers"]}, 400

    try:
        floats = [float(value) for value in descriptor]
    except (TypeError, ValueError):
        return {"errors": ["descriptor values must be numbers"]}, 400

    try:
        from app.controllers.face_controller import upsert_student_face_embedding

        upsert_student_face_embedding(student, floats)
        db.session.commit()
        db.session.refresh(student)
        return {
            "success": True,
            "student": student.to_dict(),
            "message": "Face descriptor saved successfully",
        }, 200
    except Exception as exc:
        db.session.rollback()
        print(f"[FACE] Failed to save descriptor for student_id={student_id}: {exc}")
        return {"errors": ["Failed to save face descriptor"]}, 500
