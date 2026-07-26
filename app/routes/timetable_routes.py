from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.timetable_controller import (
    delete_timetable,
    list_timetable,
    upsert_timetable,
)
from app.utils.timetable_security import require_timetable_read, require_timetable_write

timetable_bp = Blueprint("timetable", __name__, url_prefix="/api/timetable")


@timetable_bp.get("")
@timetable_bp.get("/")
@jwt_required()
@require_timetable_read
def list_slots():
    """Read timetable slots, always filtered by the caller's tenantId."""
    result, status = list_timetable(
        classroom_id=request.args.get("classroomId") or request.args.get("classroom_id"),
        student_id=request.args.get("studentId") or request.args.get("student_id"),
    )
    return result, status


@timetable_bp.post("")
@timetable_bp.post("/")
@jwt_required()
@require_timetable_write
def create_or_update():
    """Create or update a schedule slot (admin/teacher only)."""
    body = request.get_json(silent=True) or {}
    result, status = upsert_timetable(body)
    return result, status


@timetable_bp.delete("/<int:slot_id>")
@jwt_required()
@require_timetable_write
def remove(slot_id):
    """Delete a schedule slot (admin/teacher only, same tenant)."""
    result, status = delete_timetable(slot_id)
    return result, status
