from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.classroom_controller import create_classroom, list_classrooms
from app.middleware import get_current_user, role_required

classroom_bp = Blueprint("classrooms", __name__, url_prefix="/api/classrooms")


@classroom_bp.get("")
@jwt_required()
@role_required("super_admin", "institution_admin", "teacher")
def list_all():
    user = get_current_user()
    result, status = list_classrooms(user)
    return result, status


@classroom_bp.post("")
@jwt_required()
@role_required("institution_admin")
def create():
    user = get_current_user()
    result, status = create_classroom(request.get_json(silent=True) or {}, user)
    return result, status
