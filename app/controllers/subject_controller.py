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
    description = (data.get("description") or "").strip() or None

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
            description=description,
            is_active=bool(data.get("is_active", data.get("isActive", True))),
        )
        db.session.add(subject)
        db.session.flush()
        monthly_fee_raw = data.get("monthly_fee", data.get("monthlyFee"))
        if monthly_fee_raw is not None and str(monthly_fee_raw).strip() != "":
            from app.controllers.tuition_controller import ZERO, _decimal, _parse_date
            from app.models import SubjectFee
            from app.utils import local_today

            monthly_fee = _decimal(monthly_fee_raw)
            effective_from = _parse_date(
                data.get("effective_from", data.get("effectiveFrom")),
                local_today().replace(day=1),
            )
            if monthly_fee is None or monthly_fee < ZERO or not effective_from:
                db.session.rollback()
                return {"errors": ["Invalid monthly fee or effective date"]}, 400
            db.session.add(SubjectFee(
                institution_id=institution_id,
                subject_id=subject.id,
                monthly_fee=monthly_fee,
                currency=str(data.get("currency") or "LKR").upper()[:3],
                effective_from=effective_from.replace(day=1),
                is_active=True,
                description=description,
                created_by=user.id,
            ))
        db.session.commit()
        return {"subject": subject.to_dict()}, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to create subject"]}, 500


def update_subject(subject_id, data, user):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    subject = Subject.query.filter_by(id=subject_id, institution_id=user.institution_id).first()
    if not subject:
        return {"errors": ["Subject not found"]}, 404
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return {"errors": ["Subject name is required"]}, 400
        duplicate = Subject.query.filter(
            Subject.institution_id == user.institution_id,
            Subject.id != subject.id,
            func.lower(Subject.name) == name.lower(),
        ).first()
        if duplicate:
            return {"errors": ["A subject with this name already exists"]}, 409
        subject.name = name
    if "code" in data:
        subject.code = str(data.get("code") or "").strip() or None
    if "description" in data:
        subject.description = str(data.get("description") or "").strip() or None
    if "is_active" in data or "isActive" in data:
        subject.is_active = bool(data.get("is_active", data.get("isActive")))
    try:
        db.session.commit()
        return {"subject": subject.to_dict()}, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to update subject"]}, 500
