from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.parent_controller import (
    get_parent_attendance,
    get_parent_children,
    parent_login,
)
from app.middleware import get_current_user, role_required

parent_bp = Blueprint("parent", __name__, url_prefix="/api/parent")


@parent_bp.post("/login")
def login():
    result, status = parent_login(request.get_json(silent=True) or {})
    return result, status


@parent_bp.get("/children")
@jwt_required()
@role_required("parent")
def children():
    user = get_current_user()
    result, status = get_parent_children(user)
    return result, status


@parent_bp.get("/attendance")
@jwt_required()
@role_required("parent")
def attendance():
    user = get_current_user()
    result, status = get_parent_attendance(
        user,
        student_id=request.args.get("student_id"),
        month=request.args.get("month"),
        year=request.args.get("year"),
    )
    return result, status
