from flask import Blueprint, request, send_file
import io

from flask_jwt_extended import jwt_required

from app.controllers.attendance_controller import (
    get_classroom_attendance,
    get_student_attendance,
    mark_attendance,
)
from app.middleware import get_current_user, role_required
from app.models import Attendance, Classroom
from app.utils.pdf_utils import generate_attendance_pdf

attendance_bp = Blueprint("attendance", __name__, url_prefix="/api/attendance")


@attendance_bp.post("/mark")
@jwt_required()
@role_required("teacher")
def mark():
    user = get_current_user()
    result, status = mark_attendance(request.get_json(silent=True) or {}, user)
    return result, status


@attendance_bp.get("/classroom/<int:classroom_id>")
@jwt_required()
@role_required("teacher", "institution_admin", "super_admin")
def classroom_attendance(classroom_id):
    user = get_current_user()
    result, status = get_classroom_attendance(classroom_id, user)
    return result, status


@attendance_bp.get("/student/<int:student_id>")
@jwt_required()
@role_required("student", "parent", "teacher", "institution_admin", "super_admin")
def student_attendance(student_id):
    user = get_current_user()
    result, status = get_student_attendance(student_id, user)
    return result, status


@attendance_bp.get("/classroom/<int:classroom_id>/export/pdf")
@jwt_required()
@role_required("teacher", "institution_admin")
def export_pdf(classroom_id):
    user = get_current_user()
    classroom = Classroom.query.get(classroom_id)
    if not classroom:
        return {"errors": ["Classroom not found"]}, 404

    records = Attendance.query.filter_by(classroom_id=classroom_id).order_by(Attendance.date.desc()).limit(100).all()
    pdf_bytes = generate_attendance_pdf(
        institution_name=classroom.institution.name if classroom.institution else "Institution",
        classroom_name=classroom.name,
        date_range="Recent Records",
        records=[r.to_dict() for r in records],
    )
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"attendance_{classroom_id}.pdf",
    )
