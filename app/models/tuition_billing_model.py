from decimal import Decimal

from app.extensions import db
from app.utils import to_iso, utc_now


MONEY_ZERO = Decimal("0.00")


def money(value):
    return float(value or MONEY_ZERO)


class SubjectFee(db.Model):
    __tablename__ = "subject_fees"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    monthly_fee = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="LKR", server_default="LKR")
    effective_from = db.Column(db.Date, nullable=False, index=True)
    effective_to = db.Column(db.Date, nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    subject = db.relationship("Subject", lazy=True)

    __table_args__ = (
        db.UniqueConstraint(
            "institution_id", "subject_id", "effective_from", name="uq_subject_fee_effective"
        ),
        db.Index("ix_subject_fee_lookup", "institution_id", "subject_id", "effective_from", "effective_to"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "subject_id": self.subject_id,
            "subjectId": self.subject_id,
            "subject_name": self.subject.name if self.subject else None,
            "subjectName": self.subject.name if self.subject else None,
            "monthly_fee": money(self.monthly_fee),
            "monthlyFee": money(self.monthly_fee),
            "currency": self.currency,
            "effective_from": self.effective_from.isoformat(),
            "effectiveFrom": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "effectiveTo": self.effective_to.isoformat() if self.effective_to else None,
            "is_active": self.is_active,
            "isActive": self.is_active,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
        }


class StudentSubjectEnrollment(db.Model):
    __tablename__ = "student_subject_enrollments"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=True, index=True)
    fee_snapshot = db.Column(db.Numeric(12, 2), nullable=True)
    discount_amount = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO, server_default="0")
    discount_note = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    student = db.relationship("Student", lazy=True)
    subject = db.relationship("Subject", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("student_id", "subject_id", "start_date", name="uq_student_subject_start"),
        db.Index("ix_student_enrollment_active", "institution_id", "student_id", "is_active"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "student_id": self.student_id,
            "subject_id": self.subject_id,
            "subjectId": self.subject_id,
            "subject_name": self.subject.name if self.subject else None,
            "subjectName": self.subject.name if self.subject else None,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "fee_snapshot": money(self.fee_snapshot) if self.fee_snapshot is not None else None,
            "feeSnapshot": money(self.fee_snapshot) if self.fee_snapshot is not None else None,
            "discount_amount": money(self.discount_amount),
            "discountAmount": money(self.discount_amount),
            "discount_note": self.discount_note,
            "is_active": self.is_active,
        }


class MonthlyInvoice(db.Model):
    __tablename__ = "monthly_invoices"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    billing_period = db.Column(db.String(7), nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False, default="LKR", server_default="LKR")
    subject_charges = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    previous_balance = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    discount_amount = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    waived_amount = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    net_total = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    paid_amount = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    applied_credit = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    balance_due = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    status = db.Column(db.String(24), nullable=False, default="UNPAID", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    student = db.relationship("Student", lazy=True)
    lines = db.relationship("InvoiceLineItem", backref="invoice", lazy=True, cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("institution_id", "student_id", "billing_period", name="uq_monthly_invoice"),
        db.Index("ix_invoice_tenant_period_status", "institution_id", "billing_period", "status"),
    )

    def to_dict(self, include_lines=True):
        payload = {
            "id": self.id,
            "institution_id": self.institution_id,
            "student_id": self.student_id,
            "studentId": self.student_id,
            "student_name": self.student.user.full_name if self.student and self.student.user else None,
            "registration_no": self.student.registration_no if self.student else None,
            "grade": self.student.grade if self.student else None,
            "billing_period": self.billing_period,
            "billingPeriod": self.billing_period,
            "currency": self.currency,
            "subject_charges": money(self.subject_charges),
            "previous_balance": money(self.previous_balance),
            "discount_amount": money(self.discount_amount),
            "waived_amount": money(self.waived_amount),
            "net_total": money(self.net_total),
            "paid_amount": money(self.paid_amount),
            "applied_credit": money(self.applied_credit),
            "balance_due": money(self.balance_due),
            "status": self.status,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
        }
        if include_lines:
            payload["lines"] = [line.to_dict() for line in self.lines]
        return payload


class InvoiceLineItem(db.Model):
    __tablename__ = "invoice_line_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("monthly_invoices.id"), nullable=False, index=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("student_subject_enrollments.id"), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    subject_name = db.Column(db.String(120), nullable=False)
    fee_amount = db.Column(db.Numeric(12, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    waived_amount = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    net_amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), nullable=False, default=MONEY_ZERO)
    status = db.Column(db.String(24), nullable=False, default="UNPAID")

    subject = db.relationship("Subject", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("invoice_id", "subject_id", name="uq_invoice_subject_line"),
    )

    def to_dict(self):
        balance = max(MONEY_ZERO, Decimal(self.net_amount or 0) - Decimal(self.paid_amount or 0))
        return {
            "id": self.id,
            "subject_id": self.subject_id,
            "subjectId": self.subject_id,
            "subject_name": self.subject_name,
            "subjectName": self.subject_name,
            "fee_amount": money(self.fee_amount),
            "discount_amount": money(self.discount_amount),
            "waived_amount": money(self.waived_amount),
            "net_amount": money(self.net_amount),
            "paid_amount": money(self.paid_amount),
            "balance_due": money(balance),
            "status": self.status,
        }


class TuitionPayment(db.Model):
    __tablename__ = "tuition_payments"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("monthly_invoices.id"), nullable=True, index=True)
    billing_period = db.Column(db.String(7), nullable=True, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_method = db.Column(db.String(24), nullable=False)
    reference_number = db.Column(db.String(120), nullable=True)
    receipt_number = db.Column(db.String(80), nullable=True, unique=True, index=True)
    payment_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(24), nullable=False, default="COMPLETED", index=True)
    idempotency_key = db.Column(db.String(100), nullable=False)
    parent_payment_id = db.Column(db.Integer, db.ForeignKey("tuition_payments.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    student = db.relationship("Student", lazy=True)
    recorder = db.relationship("User", foreign_keys=[recorded_by], lazy=True)
    invoice = db.relationship("MonthlyInvoice", lazy=True)
    allocations = db.relationship("PaymentAllocation", backref="payment", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("institution_id", "idempotency_key", name="uq_payment_idempotency"),
        db.Index("ix_tuition_payment_tenant_date", "institution_id", "payment_date", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "student_id": self.student_id,
            "student_name": self.student.user.full_name if self.student and self.student.user else None,
            "invoice_id": self.invoice_id,
            "billing_period": self.billing_period,
            "subject_id": self.subject_id,
            "amount": money(self.amount),
            "payment_method": self.payment_method,
            "reference_number": self.reference_number,
            "receipt_number": self.receipt_number,
            "payment_date": self.payment_date.isoformat(),
            "notes": self.notes,
            "recorded_by": self.recorded_by,
            "recorded_by_name": self.recorder.full_name if self.recorder else None,
            "status": self.status,
            "created_at": to_iso(self.created_at),
            "allocations": [item.to_dict() for item in self.allocations],
        }


class PaymentAllocation(db.Model):
    __tablename__ = "payment_allocations"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("tuition_payments.id"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("monthly_invoices.id"), nullable=False, index=True)
    invoice_line_id = db.Column(db.Integer, db.ForeignKey("invoice_line_items.id"), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "invoice_line_id": self.invoice_line_id,
            "amount": money(self.amount),
        }


class AdvanceCreditLedger(db.Model):
    __tablename__ = "advance_credit_ledger"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("tuition_payments.id"), nullable=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("monthly_invoices.id"), nullable=True)
    entry_type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    notes = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (db.Index("ix_credit_student_created", "institution_id", "student_id", "created_at"),)


class FinancialAuditLog(db.Model):
    __tablename__ = "financial_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)


class FeeReceipt(db.Model):
    __tablename__ = "fee_receipts"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("tuition_payments.id"), nullable=False, unique=True)
    receipt_number = db.Column(db.String(80), nullable=False, unique=True, index=True)
    snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    payment = db.relationship("TuitionPayment", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "payment_id": self.payment_id,
            "receipt_number": self.receipt_number,
            "snapshot": self.snapshot,
            "created_at": to_iso(self.created_at),
        }
