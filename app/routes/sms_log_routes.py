from flask import Blueprint
from flask_jwt_extended import jwt_required

from app.controllers.sms_log_controller import list_sms_logs
from app.middleware import get_current_user, role_required

sms_log_bp = Blueprint("sms_logs", __name__, url_prefix="/api/sms-logs")


@sms_log_bp.get("")
@jwt_required()
@role_required("institution_admin", "super_admin")
def list_all():
    user = get_current_user()
    result, status = list_sms_logs(user)
    return result, status
