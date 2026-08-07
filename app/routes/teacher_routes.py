from flask import Blueprint, request, send_file
import io

from flask_jwt_extended import jwt_required

from app.controllers.teacher_controller import (
    delete_teacher_student_face,
    export_teacher_attendance_history,
    get_teacher_attendance_overview,
    get_teacher_student_face_status,
    register_teacher_student_face,
    update_teacher_student_face,
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


@teacher_bp.post("/students/<int:student_id>/register-face")
@jwt_required()
@role_required("teacher")
def register_student_face(student_id):
    user = get_current_user()
    result, status = register_teacher_student_face(
        student_id, request.get_json(silent=True) or {}, user
    )
    return result, status


@teacher_bp.put("/students/<int:student_id>/update-face")
@jwt_required()
@role_required("teacher")
def update_student_face(student_id):
    user = get_current_user()
    result, status = update_teacher_student_face(
        student_id, request.get_json(silent=True) or {}, user
    )
    return result, status


@teacher_bp.delete("/students/<int:student_id>/delete-face")
@jwt_required()
@role_required("teacher")
def delete_student_face(student_id):
    user = get_current_user()
    result, status = delete_teacher_student_face(student_id, user)
    return result, status


@teacher_bp.get("/students/<int:student_id>/face-status")
@jwt_required()
@role_required("teacher")
def student_face_status(student_id):
    user = get_current_user()
    result, status = get_teacher_student_face_status(student_id, user)
    return result, status
