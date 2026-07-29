from app.extensions import db
from app.models import Institution, User

MIN_PASSWORD_LENGTH = 8


def _password_errors(password, field_label="Password"):
    text = "" if password is None else str(password)
    if not text:
        return [f"{field_label} is required"]
    if len(text) < MIN_PASSWORD_LENGTH:
        return [f"{field_label} must be at least {MIN_PASSWORD_LENGTH} characters"]
    return []


def _primary_institution_admin(institution_id):
    return (
        User.query.filter_by(institution_id=institution_id, role="institution_admin")
        .order_by(User.id.asc())
        .first()
    )


def get_institution_detail(institution_id):
    institution = Institution.query.get(institution_id)
    if not institution:
        return {"errors": ["Institution not found"]}, 404

    admin = _primary_institution_admin(institution_id)
    payload = {
        "institution": institution.to_dict(),
        "admin": admin.to_dict() if admin else None,
    }
    return payload, 200


def change_institution_admin_password(institution_id, data):
    institution = Institution.query.get(institution_id)
    if not institution:
        return {"errors": ["Institution not found"]}, 404

    admin = _primary_institution_admin(institution_id)
    if not admin:
        return {"errors": ["Institution admin account not found"]}, 404

    new_password = data.get("new_password")
    errors = _password_errors(new_password, "New password")
    if errors:
        return {"errors": errors}, 400

    try:
        admin.set_password(new_password)
        if not admin.check_password(new_password):
            db.session.rollback()
            return {"errors": ["Failed to hash password"]}, 500
        db.session.commit()
        return {
            "message": "Admin password updated successfully",
            "admin": admin.to_dict(),
        }, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to update admin password"]}, 500
