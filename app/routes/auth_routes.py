from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.auth_controller import (
    get_authenticated_user,
    login_user,
    register_institution,
    register_user,
)
from app.middleware import get_current_user, role_required

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/login")
def login():
    result, status = login_user(request.get_json(silent=True) or {})
    return result, status


@auth_bp.get("/me")
@jwt_required()
def me():
    user = get_current_user()
    result, status = get_authenticated_user(user)
    return result, status


@auth_bp.post("/register-institution")
def register_institution_route():
    result, status = register_institution(request.get_json(silent=True) or {})
    return result, status


@auth_bp.post("/register")
@jwt_required()
@role_required("super_admin", "institution_admin")
def register_route():
    user = get_current_user()
    result, status = register_user(request.get_json(silent=True) or {}, user)
    return result, status
