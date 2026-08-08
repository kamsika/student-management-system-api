from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.subject_controller import create_subject, list_subjects, update_subject
from app.middleware import get_current_user, role_required

subject_bp = Blueprint("subjects", __name__, url_prefix="/api/subjects")


@subject_bp.get("")
@jwt_required()
@role_required("super_admin", "institution_admin", "teacher")
def list_all():
    user = get_current_user()
    result, status = list_subjects(user)
    return result, status


@subject_bp.post("")
@jwt_required()
@role_required("institution_admin", "super_admin")
def create():
    user = get_current_user()
    result, status = create_subject(request.get_json(silent=True) or {}, user)
    return result, status


@subject_bp.put("/<int:subject_id>")
@jwt_required()
@role_required("institution_admin", "teacher")
def update(subject_id):
    result, status = update_subject(subject_id, request.get_json(silent=True) or {}, get_current_user())
    return result, status
