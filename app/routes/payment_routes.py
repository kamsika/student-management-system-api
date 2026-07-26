from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.controllers.payment_controller import (
    create_payment,
    get_current_student_payment,
    get_student_payment_history,
    list_payments,
    update_payment,
)
from app.middleware import get_current_user, role_required

payment_bp = Blueprint("payments", __name__, url_prefix="/api/payments")


@payment_bp.get("")
@jwt_required()
@role_required("institution_admin", "super_admin", "teacher")
def list_all():
    """List payment records for the admin Fee Management table."""
    user = get_current_user()
    result, status = list_payments(
        user,
        month=request.args.get("month"),
        year=request.args.get("year"),
        status=request.args.get("status") or request.args.get("payment_status"),
        search=request.args.get("search") or request.args.get("q"),
        student_id=request.args.get("student_id") or request.args.get("studentId"),
    )
    return result, status


@payment_bp.post("")
@jwt_required()
@role_required("institution_admin", "super_admin", "teacher")
def create():
    """Add a monthly fee payment record."""
    user = get_current_user()
    result, status = create_payment(request.get_json(silent=True) or {}, user)
    return result, status


@payment_bp.get("/student/<int:student_id>")
@jwt_required()
@role_required("institution_admin", "super_admin", "teacher")
def student_history(student_id):
    """Get payment history for one student."""
    user = get_current_user()
    result, status = get_student_payment_history(student_id, user)
    return result, status


@payment_bp.get("/current/<int:student_id>")
@jwt_required()
@role_required("institution_admin", "super_admin", "teacher")
def current_status(student_id):
    """Get current month payment status for one student."""
    user = get_current_user()
    result, status = get_current_student_payment(student_id, user)
    return result, status


@payment_bp.put("/<int:payment_id>")
@jwt_required()
@role_required("institution_admin", "super_admin", "teacher")
def update(payment_id):
    """Update payment status / amount / date."""
    user = get_current_user()
    result, status = update_payment(payment_id, request.get_json(silent=True) or {}, user)
    return result, status
