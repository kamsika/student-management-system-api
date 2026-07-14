from flask import Blueprint, request, Response
from flask_jwt_extended import jwt_required

from app.controllers.student_controller import (
    get_import_template,
    get_parent_children,
    import_students,
    list_students,
    list_teachers,
)
from app.middleware import get_current_user, role_required

student_bp = Blueprint("students", __name__, url_prefix="/api/students")


@student_bp.get("")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def list_all():
    user = get_current_user()
    result, status = list_students(user)
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
