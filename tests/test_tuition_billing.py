from datetime import date
from decimal import Decimal

import pytest
from flask import Flask

from app.controllers import tuition_controller
from app.extensions import db
from app.models import Institution, MonthlyInvoice, Student, StudentSubjectEnrollment, Subject, User


@pytest.fixture()
def billing_data():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        institution = Institution(name="Alpha", subdomain="alpha")
        other_institution = Institution(name="Beta", subdomain="beta")
        db.session.add_all([institution, other_institution])
        db.session.flush()

        def user(email, role, center, name):
            row = User(institution_id=center.id, email=email, role=role, full_name=name, password="hash")
            db.session.add(row)
            db.session.flush()
            return row

        admin = user("admin@alpha.test", "institution_admin", institution, "Admin")
        teacher = user("teacher@alpha.test", "teacher", institution, "Teacher")
        parent = user("parent@alpha.test", "parent", institution, "Parent")
        student_user = user("student@alpha.test", "student", institution, "Student")
        other_admin = user("admin@beta.test", "institution_admin", other_institution, "Other Admin")
        other_parent = user("parent@beta.test", "parent", other_institution, "Other Parent")
        subject = Subject(institution_id=institution.id, name="Mathematics")
        other_subject = Subject(institution_id=other_institution.id, name="Mathematics")
        db.session.add_all([subject, other_subject])
        db.session.flush()
        student = Student(
            institution_id=institution.id, user_id=student_user.id, parent_id=parent.id,
            registration_no="STU-001", grade="10", enrolled_subjects=["Mathematics"],
        )
        db.session.add(student)
        db.session.commit()
        yield {
            "admin": admin, "teacher": teacher, "parent": parent, "other_admin": other_admin,
            "other_parent": other_parent, "student": student, "subject": subject,
        }
        db.session.remove()
        db.drop_all()


def _configure_and_enroll(data, amount="2000.00"):
    result, status = tuition_controller.configure_subject_fee(
        data["subject"].id,
        {"monthly_fee": amount, "effective_from": "2026-08-01"},
        data["admin"],
    )
    assert status == 201, result
    db.session.add(StudentSubjectEnrollment(
        institution_id=data["admin"].institution_id,
        student_id=data["student"].id,
        subject_id=data["subject"].id,
        start_date=date(2026, 8, 1),
        fee_snapshot=Decimal(amount),
    ))
    db.session.commit()


def test_admin_fee_configuration_and_teacher_denial(billing_data):
    result, status = tuition_controller.configure_subject_fee(
        billing_data["subject"].id,
        {"monthly_fee": "2000.00", "effective_from": "2026-08-01"},
        billing_data["teacher"],
    )
    assert status == 403
    result, status = tuition_controller.configure_subject_fee(
        billing_data["subject"].id,
        {"monthly_fee": "2000.00", "effective_from": "2026-08-01"},
        billing_data["admin"],
    )
    assert status == 201
    assert result["subject_fee"]["monthly_fee"] == 2000.0


def test_cross_institution_fee_access_is_denied(billing_data):
    result, status = tuition_controller.configure_subject_fee(
        billing_data["subject"].id,
        {"monthly_fee": "2000", "effective_from": "2026-08-01"},
        billing_data["other_admin"],
    )
    assert status == 404


def test_registration_preview_totals_and_discount(billing_data):
    _configure_and_enroll(billing_data)
    preview = tuition_controller.fee_preview(
        ["Mathematics"], billing_data["admin"].institution_id, date(2026, 8, 1), Decimal("200")
    )
    assert preview["monthly_fee"] == 2000.0
    assert preview["discount"] == 200.0
    assert preview["net_monthly_fee"] == 1800.0


def test_invoice_is_idempotent_and_fee_history_does_not_change_snapshot(billing_data):
    _configure_and_enroll(billing_data)
    first, status = tuition_controller.generate_invoice(
        billing_data["student"].id, "2026-08", billing_data["admin"]
    )
    assert status == 201
    second, status = tuition_controller.generate_invoice(
        billing_data["student"].id, "2026-08", billing_data["admin"]
    )
    assert status == 200
    assert first["invoice"]["id"] == second["invoice"]["id"]
    tuition_controller.configure_subject_fee(
        billing_data["subject"].id,
        {"monthly_fee": "2500", "effective_from": "2026-09-01"},
        billing_data["admin"],
    )
    invoice = db.session.get(MonthlyInvoice, first["invoice"]["id"])
    assert invoice.lines[0].fee_amount == Decimal("2000.00")


def test_monthly_batch_generation_is_idempotent(billing_data):
    _configure_and_enroll(billing_data)
    first, status = tuition_controller.generate_institution_invoices(
        billing_data["admin"], "2026-08"
    )
    assert status == 200
    assert first == {"billing_period": "2026-08", "created": 1, "existing": 0, "failed": 0}
    second, status = tuition_controller.generate_institution_invoices(
        billing_data["admin"], "2026-08"
    )
    assert status == 200
    assert second["created"] == 0
    assert second["existing"] == 1


def test_partial_full_and_overpayment_credit_with_idempotency(billing_data):
    _configure_and_enroll(billing_data, "3500.00")
    tuition_controller.generate_invoice(billing_data["student"].id, "2026-08", billing_data["admin"])
    partial, status = tuition_controller.record_tuition_payment(
        {"student_id": billing_data["student"].id, "amount": "2000", "payment_method": "CASH"},
        billing_data["teacher"], "partial-1",
    )
    assert status == 201
    invoice = MonthlyInvoice.query.first()
    assert invoice.balance_due == Decimal("1500.00")
    assert invoice.status == "PARTIALLY_PAID"
    duplicate, status = tuition_controller.record_tuition_payment(
        {"student_id": billing_data["student"].id, "amount": "2000", "payment_method": "CASH"},
        billing_data["teacher"], "partial-1",
    )
    assert status == 200
    assert duplicate["payment"]["id"] == partial["payment"]["id"]
    tuition_controller.record_tuition_payment(
        {"student_id": billing_data["student"].id, "amount": "2000", "payment_method": "CARD"},
        billing_data["teacher"], "final-1",
    )
    db.session.refresh(invoice)
    assert invoice.balance_due == Decimal("0.00")
    assert invoice.status == "OVERPAID"
    assert tuition_controller._credit_balance(billing_data["student"].id, billing_data["admin"].institution_id) == Decimal("500.00")


def test_credit_applies_to_next_invoice_and_pending_summary(billing_data):
    _configure_and_enroll(billing_data, "1000.00")
    tuition_controller.generate_invoice(billing_data["student"].id, "2026-08", billing_data["admin"])
    tuition_controller.record_tuition_payment(
        {"student_id": billing_data["student"].id, "amount": "1500", "payment_method": "CASH"},
        billing_data["teacher"], "overpay",
    )
    result, status = tuition_controller.generate_invoice(
        billing_data["student"].id, "2026-09", billing_data["admin"]
    )
    assert status == 201
    assert result["invoice"]["applied_credit"] == 500.0
    assert result["invoice"]["balance_due"] == 500.0
    summary, status = tuition_controller.student_fee_summary(
        billing_data["student"].id, billing_data["teacher"], "2026-09"
    )
    assert status == 200
    assert summary["fee_summary"]["overall_status"] == "PENDING"


def test_refunded_payment_is_removed_and_teacher_cannot_refund(billing_data):
    _configure_and_enroll(billing_data, "1000.00")
    tuition_controller.generate_invoice(billing_data["student"].id, "2026-08", billing_data["admin"])
    result, _ = tuition_controller.record_tuition_payment(
        {"student_id": billing_data["student"].id, "amount": "1000", "payment_method": "CASH"},
        billing_data["teacher"], "refund-me",
    )
    payment_id = result["payment"]["id"]
    _, status = tuition_controller.change_payment_status(payment_id, {"status": "REFUNDED"}, billing_data["teacher"])
    assert status == 403
    _, status = tuition_controller.change_payment_status(payment_id, {"status": "REFUNDED"}, billing_data["admin"])
    assert status == 200
    invoice = MonthlyInvoice.query.first()
    assert invoice.balance_due == Decimal("1000.00")
    assert invoice.status == "UNPAID"


def test_parent_and_cross_parent_summary_scope(billing_data):
    _configure_and_enroll(billing_data)
    tuition_controller.generate_invoice(billing_data["student"].id, "2026-08", billing_data["admin"])
    _, status = tuition_controller.student_fee_summary(
        billing_data["student"].id, billing_data["parent"], "2026-08", allow_parent=True
    )
    assert status == 200
    _, status = tuition_controller.student_fee_summary(
        billing_data["student"].id, billing_data["other_parent"], "2026-08", allow_parent=True
    )
    assert status == 404
