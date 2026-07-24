from flask import Blueprint, request, send_file
import io

from flask_jwt_extended import jwt_required

from app.controllers.attendance_controller import (
    get_classroom_attendance,
    get_student_attendance,
    get_today_center_attendance,
    mark_attendance,
    scan_center_attendance,
)
from app.middleware import get_current_user, role_required
from app.models import Attendance, Classroom
from app.utils import parse_attendance_date
from app.utils.pdf_utils import generate_attendance_pdf

attendance_bp = Blueprint("attendance", __name__, url_prefix="/api/attendance")


@attendance_bp.post("/mark")
@jwt_required()
@role_required("teacher")
def mark():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    print(f"[ATTENDANCE] /mark Received attendance request for ID: {body.get('student_id')!r}")
    result, status = mark_attendance(body, user)
    return result, status


@attendance_bp.post("/scan")
@jwt_required()
@role_required("teacher")
def scan():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    print(f"[ATTENDANCE] /scan Received attendance request for ID: {body.get('student_id')!r}")
    result, status = scan_center_attendance(body, user)
    return result, status


@attendance_bp.get("/today")
@jwt_required()
@role_required("teacher", "institution_admin", "super_admin")
def today_attendance():
    """List center attendance for a date (default: today). Optional classroom_id filter."""
    user = get_current_user()
    result, status = get_today_center_attendance(
        user,
        date_str=request.args.get("date"),
        classroom_id=request.args.get("classroom_id"),
    )
    return result, status


@attendance_bp.get("/classroom/<int:classroom_id>")
@jwt_required()
@role_required("teacher", "institution_admin", "super_admin")
def classroom_attendance(classroom_id):
    user = get_current_user()
    result, status = get_classroom_attendance(
        classroom_id,
        user,
        date_str=request.args.get("date"),
    )
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

    if user.role == "teacher" and (
        classroom.teacher_id != user.id or classroom.institution_id != user.institution_id
    ):
        return {"errors": ["Access denied"]}, 403
    if user.role == "institution_admin" and classroom.institution_id != user.institution_id:
        return {"errors": ["Access denied"]}, 403

    date_str = request.args.get("date")
    query = Attendance.query.filter_by(classroom_id=classroom_id)
    date_label = "Recent Records"
    if date_str:
        attendance_date, date_error = parse_attendance_date(date_str)
        if date_error:
            return {"errors": [date_error]}, 400
        query = query.filter_by(date=attendance_date)
        date_label = attendance_date.isoformat()
        records = query.order_by(Attendance.arrival_time.desc(), Attendance.id.desc()).all()
    else:
        records = query.order_by(Attendance.date.desc()).limit(100).all()

    pdf_bytes = generate_attendance_pdf(
        institution_name=classroom.institution.name if classroom.institution else "Institution",
        classroom_name=classroom.name,
        date_range=date_label,
        records=[r.to_dict() for r in records],
    )
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"attendance_{classroom_id}.pdf",
    )
