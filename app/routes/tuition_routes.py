from flask import Blueprint, request, send_file
import io
from flask_jwt_extended import jwt_required

from app.controllers.tuition_controller import (
    billing_dashboard,
    adjust_invoice,
    change_payment_status,
    configure_subject_fee,
    generate_invoice,
    generate_institution_invoices,
    get_receipt,
    receipt_pdf,
    list_invoices,
    list_credit_ledger,
    list_financial_audit,
    list_subject_fees,
    list_tuition_payments,
    preview_registration_fees,
    record_tuition_payment,
    student_fee_summary,
    student_fee_history,
)
from app.middleware import get_current_user, role_required


tuition_bp = Blueprint("tuition", __name__, url_prefix="/api/tuition")


@tuition_bp.get("/subject-fees")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def subject_fees():
    return list_subject_fees(get_current_user(), request.args.get("subject_id"), request.args.get("history") == "true")


@tuition_bp.post("/subjects/<int:subject_id>/fees")
@jwt_required()
@role_required("institution_admin", "teacher")
def configure_fee(subject_id):
    return configure_subject_fee(subject_id, request.get_json(silent=True) or {}, get_current_user())


@tuition_bp.post("/registration-preview")
@jwt_required()
@role_required("institution_admin", "teacher")
def registration_preview():
    return preview_registration_fees(request.get_json(silent=True) or {}, get_current_user())


@tuition_bp.post("/invoices/generate")
@jwt_required()
@role_required("institution_admin", "teacher")
def create_invoice():
    data = request.get_json(silent=True) or {}
    return generate_invoice(data.get("student_id", data.get("studentId")), data.get("billing_period", data.get("billingPeriod")), get_current_user())


@tuition_bp.post("/invoices/generate-all")
@jwt_required()
@role_required("institution_admin")
def create_all_invoices():
    data = request.get_json(silent=True) or {}
    return generate_institution_invoices(get_current_user(), data.get("billing_period", data.get("billingPeriod")))


@tuition_bp.get("/invoices")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def invoices():
    return list_invoices(get_current_user(), request.args.get("student_id"), request.args.get("billing_period"), request.args.get("status"))


@tuition_bp.patch("/invoices/<int:invoice_id>")
@jwt_required()
@role_required("institution_admin", "teacher")
def invoice_adjustment(invoice_id):
    return adjust_invoice(invoice_id, request.get_json(silent=True) or {}, get_current_user())


@tuition_bp.post("/payments")
@jwt_required()
@role_required("institution_admin", "teacher")
def create_payment():
    return record_tuition_payment(request.get_json(silent=True) or {}, get_current_user(), request.headers.get("Idempotency-Key"))


@tuition_bp.get("/payments")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def payments():
    return list_tuition_payments(get_current_user(), request.args.get("student_id"), request.args.get("billing_period"), request.args.get("payment_method"), request.args.get("recorded_by"))


@tuition_bp.post("/payments/<int:payment_id>/status")
@jwt_required()
@role_required("institution_admin", "teacher")
def payment_status(payment_id):
    return change_payment_status(payment_id, request.get_json(silent=True) or {}, get_current_user())


@tuition_bp.get("/receipts/<int:receipt_id>")
@jwt_required()
@role_required("institution_admin", "teacher", "parent", "super_admin")
def receipt(receipt_id):
    return get_receipt(receipt_id, get_current_user())


@tuition_bp.get("/receipts/<int:receipt_id>/pdf")
@jwt_required()
@role_required("institution_admin", "teacher", "parent", "super_admin")
def receipt_download(receipt_id):
    result, status = receipt_pdf(receipt_id, get_current_user())
    if status != 200:
        return result, status
    return send_file(io.BytesIO(result["content"]), mimetype="application/pdf", as_attachment=True, download_name=result["filename"])


@tuition_bp.get("/students/<int:student_id>/summary")
@jwt_required()
@role_required("institution_admin", "teacher", "parent", "super_admin")
def summary(student_id):
    user = get_current_user()
    return student_fee_summary(student_id, user, request.args.get("billing_period"), allow_parent=True)


@tuition_bp.get("/students/<int:student_id>/history")
@jwt_required()
@role_required("institution_admin", "teacher", "parent", "super_admin")
def history(student_id):
    return student_fee_history(student_id, get_current_user())


@tuition_bp.get("/dashboard")
@jwt_required()
@role_required("institution_admin")
def dashboard():
    return billing_dashboard(get_current_user(), request.args.get("billing_period"))


@tuition_bp.get("/credits")
@jwt_required()
@role_required("institution_admin", "teacher", "super_admin")
def credits():
    return list_credit_ledger(get_current_user(), request.args.get("student_id"))


@tuition_bp.get("/audit")
@jwt_required()
@role_required("institution_admin", "teacher")
def audit():
    return list_financial_audit(get_current_user())
