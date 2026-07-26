from flask import Blueprint, request, send_file
import io

from flask_jwt_extended import jwt_required

from app.controllers.attendance_controller import (
    create_attendance,
    get_attendance_report,
    get_classroom_attendance,
    get_manual_attendance_roster,
    get_student_attendance,
    get_today_center_attendance,
    mark_attendance,
    save_manual_attendance,
    scan_center_attendance,
)
from app.middleware import get_current_user, role_required
from app.models import Attendance, Classroom
from app.utils import parse_attendance_date
from app.utils.csv_utils import export_attendance_summary_csv
from app.utils.pdf_utils import generate_attendance_pdf, generate_attendance_summary_pdf

attendance_bp = Blueprint("attendance", __name__, url_prefix="/api/attendance")


@attendance_bp.post("")
@attendance_bp.post("/")
@jwt_required()
@role_required("teacher", "institution_admin")
def create():
    """Create today's attendance from {studentId, timestamp?, status?, classroomId?}."""
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    result, status = create_attendance(body, user)
    return result, status


@attendance_bp.post("/mark")
@jwt_required()
@role_required("teacher", "institution_admin")
def mark():
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    print(f"[ATTENDANCE] /mark Received attendance request for ID: {body.get('student_id')!r}")
    result, status = mark_attendance(body, user)
    return result, status


@attendance_bp.post("/manual")
@jwt_required()
@role_required("teacher", "institution_admin")
def manual_save():
    """Bulk upsert manual attendance for classroom + subject + date."""
    user = get_current_user()
    body = request.get_json(silent=True) or {}
    result, status = save_manual_attendance(body, user)
    return result, status


@attendance_bp.get("/manual")
@jwt_required()
@role_required("teacher", "institution_admin")
def manual_roster():
    """Fetch class roster with current status for manual marking UI."""
    user = get_current_user()
    result, status = get_manual_attendance_roster(
        user,
        classroom_id=request.args.get("classroomId") or request.args.get("classroom_id"),
        subject_name=request.args.get("subjectName") or request.args.get("subject_name"),
        date_str=request.args.get("date"),
    )
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
    result, status = get_student_attendance(
        student_id,
        user,
        classroom_id=request.args.get("classroom_id"),
        start_date_str=request.args.get("start_date"),
        end_date_str=request.args.get("end_date"),
    )
    return result, status


@attendance_bp.get("/report")
@jwt_required()
@role_required("teacher", "institution_admin", "super_admin")
def attendance_report():
    """Filtered per-student attendance summary for a classroom and date range."""
    user = get_current_user()
    result, status = get_attendance_report(
        user,
        classroom_id=request.args.get("classroom_id"),
        start_date_str=request.args.get("start_date"),
        end_date_str=request.args.get("end_date"),
    )
    return result, status


@attendance_bp.get("/report/export/csv")
@jwt_required()
@role_required("teacher", "institution_admin")
def export_report_csv():
    user = get_current_user()
    result, status = get_attendance_report(
        user,
        classroom_id=request.args.get("classroom_id"),
        start_date_str=request.args.get("start_date"),
        end_date_str=request.args.get("end_date"),
    )
    if status != 200:
        return result, status

    csv_text = export_attendance_summary_csv(result.get("students") or [])
    classroom_id = result["classroom"]["id"]
    start = result["start_date"]
    end = result["end_date"]
    return send_file(
        io.BytesIO(csv_text.encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"attendance_summary_{classroom_id}_{start}_{end}.csv",
    )


@attendance_bp.get("/report/export/pdf")
@jwt_required()
@role_required("teacher", "institution_admin")
def export_report_pdf():
    user = get_current_user()
    result, status = get_attendance_report(
        user,
        classroom_id=request.args.get("classroom_id"),
        start_date_str=request.args.get("start_date"),
        end_date_str=request.args.get("end_date"),
    )
    if status != 200:
        return result, status

    classroom = result["classroom"]
    institution_name = "Institution"
    classroom_model = Classroom.query.get(classroom["id"])
    if classroom_model and classroom_model.institution:
        institution_name = classroom_model.institution.name

    pdf_bytes = generate_attendance_summary_pdf(
        institution_name=institution_name,
        classroom_name=classroom.get("name") or f"Classroom {classroom['id']}",
        date_range=f"{result['start_date']} to {result['end_date']}",
        total_classes_held=result.get("total_classes_held", 0),
        rows=result.get("students") or [],
    )
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            f"attendance_summary_{classroom['id']}_{result['start_date']}_{result['end_date']}.pdf"
        ),
    )


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
