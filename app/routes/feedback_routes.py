from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from app.controllers.feedback_controller import history, submit
from app.middleware import get_current_user, role_required
feedback_bp=Blueprint("feedback",__name__,url_prefix="/api/admin/feedback")
@feedback_bp.post("")
@jwt_required()
@role_required("institution_admin")
def create(): return submit(get_current_user(),request.get_json(silent=True) or {})
@feedback_bp.get("")
@jwt_required()
@role_required("institution_admin")
def mine(): return history(get_current_user())
