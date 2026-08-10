from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.password_controller import (
    change_institution_admin_password,
    get_institution_detail,
)
from app.middleware import role_required
from app.controllers.feedback_controller import alerts, analytics
from app.models import InstitutionFeedback

super_admin_bp = Blueprint("super_admin", __name__, url_prefix="/api/super-admin")


@super_admin_bp.get("/institutions/<int:institution_id>")
@jwt_required()
@role_required("super_admin")
def institution_detail(institution_id):
    result, status = get_institution_detail(institution_id)
    return result, status


@super_admin_bp.put("/institutions/<int:institution_id>/change-admin-password")
@jwt_required()
@role_required("super_admin")
def change_admin_password(institution_id):
    result, status = change_institution_admin_password(
        institution_id,
        request.get_json(silent=True) or {},
    )
    return result, status

@super_admin_bp.get("/feedback")
@jwt_required()
@role_required("super_admin")
def feedback_list():
    page=max(request.args.get("page",1,type=int),1); result=InstitutionFeedback.query.order_by(InstitutionFeedback.created_at.desc()).paginate(page=page,per_page=min(request.args.get("per_page",20,type=int),100),error_out=False)
    return {"feedback":[r.to_dict() for r in result.items],"total":result.total,"pages":result.pages},200
@super_admin_bp.get("/feedback/<int:feedback_id>")
@jwt_required()
@role_required("super_admin")
def feedback_detail(feedback_id):
    row=InstitutionFeedback.query.get(feedback_id)
    if not row:return {"errors":["Feedback not found"]},404
    rows=InstitutionFeedback.query.filter_by(institution_id=row.institution_id).order_by(InstitutionFeedback.created_at.asc()).all()
    return {"feedback":row.to_dict(),"history":[r.to_dict() for r in rows]},200
@super_admin_bp.get("/feedback-analytics")
@jwt_required()
@role_required("super_admin")
def feedback_analytics():return analytics(request.args)
@super_admin_bp.get("/feedback-alerts")
@jwt_required()
@role_required("super_admin")
def feedback_alerts():return alerts(request.args)
