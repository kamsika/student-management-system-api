from flask import Blueprint, request, send_file
import io

from flask_jwt_extended import jwt_required

from app.controllers.teacher_controller import (
    export_teacher_attendance_history,
    get_teacher_attendance_overview,
)
from app.middleware import get_current_user, role_required

teacher_bp = Blueprint("teacher", __name__, url_prefix="/api/teacher")


@teacher_bp.get("/attendance")
@jwt_required()
@role_required("teacher")
def attendance_overview():
    """Teacher attendance overview for a date (default: today) and optional filters."""
    user = get_current_user()
    result, status = get_teacher_attendance_overview(
        user,
        date_str=request.args.get("date"),
        classroom_id=request.args.get("classroomId") or request.args.get("classroom_id"),
        grade=request.args.get("grade"),
        subject=request.args.get("subject") or request.args.get("subjectName"),
        search=request.args.get("search") or request.args.get("q"),
    )
    return result, status


def _export_query_args():
    return dict(
        date_str=request.args.get("date"),
        classroom_id=request.args.get("classroomId") or request.args.get("classroom_id"),
        grade=request.args.get("grade"),
        subject=request.args.get("subject") or request.args.get("subjectName"),
        search=request.args.get("search") or request.args.get("q"),
    )


@teacher_bp.get("/attendance/export/csv")
@jwt_required()
@role_required("teacher")
def attendance_export_csv():
    user = get_current_user()
    result, status = export_teacher_attendance_history(
        user, export_format="csv", **_export_query_args()
    )
    if status != 200:
        return result, status
    return send_file(
        io.BytesIO(result["content"]),
        mimetype=result["mimetype"],
        as_attachment=True,
        download_name=result["filename"],
    )


@teacher_bp.get("/attendance/export/pdf")
@jwt_required()
@role_required("teacher")
def attendance_export_pdf():
    user = get_current_user()
    result, status = export_teacher_attendance_history(
        user, export_format="pdf", **_export_query_args()
    )
    if status != 200:
        return result, status
    return send_file(
        io.BytesIO(result["content"]),
        mimetype=result["mimetype"],
        as_attachment=True,
        download_name=result["filename"],
    )
