from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.face_controller import get_student_face, list_institution_face_embeddings, recognize_face, register_face
from app.middleware import get_current_user

face_bp = Blueprint("faces", __name__, url_prefix="/api/faces")


@face_bp.post("/register")
@jwt_required()
def register():
    user = get_current_user()
    result, status = register_face(request.get_json(silent=True) or {}, user)
    return result, status


@face_bp.post("/recognize")
@jwt_required()
def recognize():
    user = get_current_user()
    result, status = recognize_face(request.get_json(silent=True) or {}, user)
    return result, status


@face_bp.get("/student/<int:student_id>")
@jwt_required()
def student_face(student_id):
    user = get_current_user()
    result, status = get_student_face(student_id, user)
    return result, status


@face_bp.get("/profiles")
@jwt_required()
def profiles():
    user = get_current_user()
    result, status = list_institution_face_embeddings(user)
    return result, status
