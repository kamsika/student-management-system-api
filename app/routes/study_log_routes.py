from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.study_log_controller import (
    get_active_session,
    get_study_analytics,
    toggle_study_session,
)
from app.middleware import get_current_user, role_required

study_log_bp = Blueprint("study_logs", __name__, url_prefix="/api/study-logs")


@study_log_bp.post("/toggle")
@jwt_required()
@role_required("student")
def toggle():
    user = get_current_user()
    result, status = toggle_study_session(user)
    return result, status


@study_log_bp.get("/analytics")
@jwt_required()
@role_required("student", "institution_admin")
def analytics():
    user = get_current_user()
    days = request.args.get("days", 30, type=int)
    result, status = get_study_analytics(user, days)
    return result, status


@study_log_bp.get("/active")
@jwt_required()
@role_required("student")
def active():
    user = get_current_user()
    result, status = get_active_session(user)
    return result, status
