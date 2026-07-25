from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.teacher_controller import get_teacher_attendance_overview
from app.middleware import get_current_user, role_required

teacher_bp = Blueprint("teacher", __name__, url_prefix="/api/teacher")


@teacher_bp.get("/attendance")
@jwt_required()
@role_required("teacher")
def attendance_overview():
    """Teacher attendance overview for a date (default: today) and optional classroom."""
    user = get_current_user()
    result, status = get_teacher_attendance_overview(
        user,
        date_str=request.args.get("date"),
        classroom_id=request.args.get("classroomId") or request.args.get("classroom_id"),
    )
    return result, status
