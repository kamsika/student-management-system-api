from flask import Blueprint, request, Response
from flask_jwt_extended import jwt_required

from app.controllers.student_controller import (
    create_student,
    get_import_template,
    get_parent_children,
    import_students,
    list_face_profiles,
    list_students,
    list_teachers,
    save_student_face,
    update_student,
    update_student_subjects,
    update_student_payment_status,
)
from app.middleware import get_current_user, role_required

student_bp = Blueprint("students", __name__, url_prefix="/api/students")


@student_bp.get("")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def list_all():
    user = get_current_user()
    result, status = list_students(
        user,
        search=request.args.get("search") or request.args.get("q"),
    )
    return result, status


@student_bp.post("")
@jwt_required()
@role_required("institution_admin")
def create_one():
    user = get_current_user()
    result, status = create_student(request.get_json(silent=True) or {}, user)
    return result, status


@student_bp.patch("/<int:student_id>")
@student_bp.put("/<int:student_id>")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def update_one(student_id):
    user = get_current_user()
    result, status = update_student(student_id, request.get_json(silent=True) or {}, user)
    return result, status


@student_bp.put("/<int:student_id>/subjects")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def update_subjects(student_id):
    """Update enrolled subjects for a specific student."""
    user = get_current_user()
    result, status = update_student_subjects(
        student_id, request.get_json(silent=True) or {}, user
    )
    return result, status


@student_bp.patch("/<int:student_id>/payment-status")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def update_payment_status(student_id):
    user = get_current_user()
    result, status = update_student_payment_status(
        student_id, request.get_json(silent=True) or {}, user
    )
    return result, status


@student_bp.post("/import")
@jwt_required()
@role_required("institution_admin")
def import_csv():
    user = get_current_user()
    if "file" in request.files:
        file_content = request.files["file"].read().decode("utf-8")
    else:
        file_content = request.get_data(as_text=True)
    result, status = import_students(file_content, user)
    return result, status


@student_bp.get("/my-children")
@jwt_required()
@role_required("parent")
def my_children():
    user = get_current_user()
    result, status = get_parent_children(user)
    return result, status


@student_bp.get("/teachers")
@jwt_required()
@role_required("institution_admin", "super_admin")
def teachers():
    user = get_current_user()
    result, status = list_teachers(user)
    return result, status


@student_bp.get("/face-profiles")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def face_profiles():
    user = get_current_user()
    result, status = list_face_profiles(user)
    return result, status


@student_bp.get("/import/template")
@jwt_required()
@role_required("institution_admin")
def template():
    content = get_import_template()
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_import_template.csv"},
    )


@student_bp.post("/<int:student_id>/face")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def save_face(student_id):
    user = get_current_user()
    result, status = save_student_face(student_id, request.get_json(silent=True) or {}, user)
    return result, status


@student_bp.put("/<int:student_id>/face")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def update_face(student_id):
    """Alias kept for older clients that used PUT."""
    user = get_current_user()
    result, status = save_student_face(student_id, request.get_json(silent=True) or {}, user)
    return result, status
