from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.institution_settings_controller import (
    get_institution_settings,
    update_institution_branding,
    update_institution_profile,
    update_notification_settings,
)
from app.controllers.password_controller import change_admin_password
from app.middleware import get_current_user, role_required

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@admin_bp.get("/settings")
@jwt_required()
@role_required("institution_admin")
def settings_get():
    user = get_current_user()
    result, status = get_institution_settings(user)
    return result, status


@admin_bp.patch("/settings/profile")
@jwt_required()
@role_required("institution_admin")
def settings_profile():
    user = get_current_user()
    result, status = update_institution_profile(user, request.get_json(silent=True) or {})
    return result, status


@admin_bp.patch("/settings/branding")
@jwt_required()
@role_required("institution_admin")
def settings_branding():
    user = get_current_user()
    result, status = update_institution_branding(user, request.get_json(silent=True) or {})
    return result, status


@admin_bp.patch("/settings/notifications")
@jwt_required()
@role_required("institution_admin")
def settings_notifications():
    user = get_current_user()
    result, status = update_notification_settings(user, request.get_json(silent=True) or {})
    return result, status


@admin_bp.put("/change-password")
@jwt_required()
@role_required("institution_admin")
def change_password():
    user = get_current_user()
    if not user:
        return {"errors": ["Unauthorized"]}, 401
    result, status = change_admin_password(user, request.get_json(silent=True) or {})
    return result, status
