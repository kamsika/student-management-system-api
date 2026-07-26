from sqlalchemy import func, or_

from app.extensions import db
from app.models import Classroom, Institution, Student, StudentPayment, Timetable, User
from app.models.student_model import normalize_enrolled_subjects
from app.utils.csv_utils import parse_students_csv, generate_students_template_csv
from app.utils.student_id_utils import build_placeholder_emails, generate_next_registration_no
from app.utils import local_today, utc_now


def _normalize_name(name: str) -> str:
    return (name or "").strip().lower()


def _normalize_contact(contact: str) -> str:
    return (contact or "").replace(" ", "").strip()


def _resolve_student_classroom(student, user=None):
    """Best-effort classroom for display (teacher class, timetable, or center default)."""
    if user is not None and user.role == "teacher" and user.institution_id:
        classroom = (
            Classroom.query.filter_by(teacher_id=user.id, institution_id=user.institution_id)
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


def _student_detail_dict(student, user=None):
    payload = student.to_dict()
    classroom = _resolve_student_classroom(student, user=user)
    payload["classroom_id"] = classroom.id if classroom else None
    payload["classroomId"] = classroom.id if classroom else None
    payload["classroom_name"] = classroom.name if classroom else None
    payload["classroomName"] = classroom.name if classroom else None
    if classroom:
        payload["classroom"] = {
            "id": classroom.id,
            "name": classroom.name,
        }
    else:
        payload["classroom"] = None
    return payload


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


def list_students(user, search=None):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    query = Student.query.join(User, Student.user_id == User.id)
    if user.role != "super_admin":
        query = query.filter(Student.institution_id == user.institution_id)

    search_text = (search or "").strip()
    if search_text:
        pattern = f"%{search_text.lower()}%"
        query = query.filter(
            or_(
                func.lower(User.full_name).like(pattern),
                func.lower(Student.registration_no).like(pattern),
            )
        )

    students = query.order_by(User.full_name.asc(), Student.registration_no.asc()).all()
    return {
        "students": [_student_detail_dict(student, user=user) for student in students],
        "count": len(students),
        "search": search_text or None,
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

    payment = StudentPayment.query.filter_by(
        student_id=student.id,
        billing_period=period,
    ).first()
    if payment is None:
        payment = StudentPayment(
            student_id=student.id,
            billing_period=period,
            payment_status=status,
            paid_at=utc_now() if status == "Paid" else None,
        )
        db.session.add(payment)
    else:
        payment.payment_status = status
        payment.paid_at = utc_now() if status == "Paid" else None

    try:
        db.session.commit()
        db.session.refresh(payment)
        return {"success": True, "payment": payment.to_dict()}, 200
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
    if user.role != "institution_admin":
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
        payload = student.to_dict(include_face_descriptor=True)
        profiles.append(
            {
                "id": payload["id"],
                "registration_no": payload["registration_no"],
                "full_name": payload["full_name"],
                "descriptor": payload.get("descriptor"),
                "has_face_descriptor": payload["has_face_descriptor"],
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
        student.face_descriptor = floats
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
