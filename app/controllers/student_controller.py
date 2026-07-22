from app.extensions import db
from app.models import Student, User
from app.utils.csv_utils import parse_students_csv, generate_students_template_csv


def list_students(user):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    query = Student.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)

    students = query.all()
    return {"students": [s.to_dict() for s in students]}, 200


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
