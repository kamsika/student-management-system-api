from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.institution_controller import (
    create_institution,
    get_institution_billing,
    list_institutions,
    update_institution_status,
)
from app.middleware import get_current_user, role_required

institution_bp = Blueprint("institutions", __name__, url_prefix="/api/institutions")


@institution_bp.post("")
@jwt_required()
@role_required("super_admin")
def create():
    result, status = create_institution(request.get_json(silent=True) or {})
    return result, status


@institution_bp.get("")
@jwt_required()
@role_required("super_admin")
def list_all():
    result, status = list_institutions()
    return result, status


@institution_bp.patch("/<int:institution_id>/status")
@jwt_required()
@role_required("super_admin")
def update_status(institution_id):
    result, status = update_institution_status(institution_id, request.get_json(silent=True) or {})
    return result, status


@institution_bp.get("/<int:institution_id>/billing")
@jwt_required()
@role_required("super_admin", "institution_admin")
def billing(institution_id):
    user = get_current_user()
    result, status = get_institution_billing(institution_id, user)
    return result, status
