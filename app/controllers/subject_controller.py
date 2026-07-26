from sqlalchemy import func

from app.extensions import db
from app.models import Subject, User


def list_subjects(user):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    if user.role != "super_admin" and not user.institution_id:
        return {"errors": ["Institution required"]}, 400

    query = Subject.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)

    subjects = query.order_by(Subject.name.asc()).all()
    return {"subjects": [item.to_dict() for item in subjects]}, 200


def create_subject(data, user):
    if user.role not in ("institution_admin", "super_admin"):
        return {"errors": ["Access denied"]}, 403
    if not user.institution_id and user.role != "super_admin":
        return {"errors": ["Institution required"]}, 400

    institution_id = user.institution_id
    if user.role == "super_admin":
        institution_id = data.get("institution_id") or data.get("institutionId") or institution_id
    if not institution_id:
        return {"errors": ["Institution required"]}, 400

    name = (data.get("name") or data.get("subjectName") or "").strip()
    code = (data.get("code") or data.get("subjectCode") or "").strip() or None
    teacher_id = data.get("teacher_id", data.get("teacherId"))

    if not name:
        return {"errors": ["Subject name is required"]}, 400
    if len(name) > 120:
        return {"errors": ["Subject name must be 120 characters or less"]}, 400
    if code and len(code) > 40:
        return {"errors": ["Subject code must be 40 characters or less"]}, 400

    existing = (
        Subject.query.filter(Subject.institution_id == institution_id)
        .filter(func.lower(Subject.name) == name.lower())
        .first()
    )
    if existing:
        return {"errors": ["A subject with this name already exists"]}, 409

    resolved_teacher_id = None
    if teacher_id is not None and str(teacher_id).strip() != "":
        try:
            resolved_teacher_id = int(teacher_id)
        except (TypeError, ValueError):
            return {"errors": ["teacher_id must be an integer"]}, 400
        teacher = User.query.filter_by(
            id=resolved_teacher_id,
            institution_id=institution_id,
            role="teacher",
        ).first()
        if not teacher:
            return {"errors": ["Teacher not found in institution"]}, 404

    try:
        subject = Subject(
            institution_id=institution_id,
            name=name,
            code=code,
            teacher_id=resolved_teacher_id,
        )
        db.session.add(subject)
        db.session.commit()
        return {"subject": subject.to_dict()}, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to create subject"]}, 500
