from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.password_controller import (
    change_institution_admin_password,
    get_institution_detail,
)
from app.middleware import role_required

super_admin_bp = Blueprint("super_admin", __name__, url_prefix="/api/super-admin")


@super_admin_bp.get("/institutions/<int:institution_id>")
@jwt_required()
@role_required("super_admin")
def institution_detail(institution_id):
    result, status = get_institution_detail(institution_id)
    return result, status


@super_admin_bp.put("/institutions/<int:institution_id>/change-admin-password")
@jwt_required()
@role_required("super_admin")
def change_admin_password(institution_id):
    result, status = change_institution_admin_password(
        institution_id,
        request.get_json(silent=True) or {},
    )
    return result, status
