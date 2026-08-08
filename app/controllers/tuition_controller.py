from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO

from sqlalchemy import func, or_

from app.extensions import db
from app.models import (
    AdvanceCreditLedger,
    FeeReceipt,
    FinancialAuditLog,
    Institution,
    InvoiceLineItem,
    MonthlyInvoice,
    PaymentAllocation,
    Student,
    StudentPayment,
    StudentSubjectEnrollment,
    Subject,
    SubjectFee,
    TuitionPayment,
    User,
)
from app.models.student_payment_model import billing_period_from_month_year
from app.utils import local_today


ZERO = Decimal("0.00")
VALID_PAYMENT_METHODS = {"CASH", "CARD", "BANK_TRANSFER", "ONLINE"}
ACTIVE_PAYMENT_STATUSES = {"COMPLETED"}


def _decimal(value, *, default=None):
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    return parsed


def _period(raw=None):
    text = str(raw or "").strip()
    if not text:
        today = local_today()
        return billing_period_from_month_year(today.month, today.year)
    try:
        year, month = (int(part) for part in text.split("-", 1))
        return billing_period_from_month_year(month, year) if 2000 <= year <= 2100 and 1 <= month <= 12 else None
    except (TypeError, ValueError):
        return None


def _period_start(period):
    return date(int(period[:4]), int(period[5:7]), 1)


def _period_end(period):
    start = _period_start(period)
    next_month = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    return next_month - timedelta(days=1)


def _parse_date(raw, default=None):
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _tenant_student(student_id, user, *, allow_parent=False):
    try:
        student = db.session.get(Student, int(student_id))
    except (TypeError, ValueError):
        return None, ({"errors": ["student_id must be an integer"]}, 400)
    if not student:
        return None, ({"errors": ["Student not found"]}, 404)
    if user.role == "super_admin":
        return student, None
    if allow_parent and user.role == "parent":
        if student.parent_id != user.id or student.institution_id != user.institution_id:
            return None, ({"errors": ["Student not found"]}, 404)
        return student, None
    if user.role not in ("institution_admin", "teacher") or student.institution_id != user.institution_id:
        return None, ({"errors": ["Access denied"]}, 403)
    return student, None


def _audit(user, action, entity_type, entity_id=None, details=None, institution_id=None):
    db.session.add(
        FinancialAuditLog(
            institution_id=institution_id or user.institution_id,
            actor_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


def current_subject_fee(subject_id, institution_id, on_date=None):
    target = on_date or local_today()
    return (
        SubjectFee.query.filter(
            SubjectFee.subject_id == subject_id,
            SubjectFee.institution_id == institution_id,
            SubjectFee.effective_from <= target,
            or_(SubjectFee.effective_to.is_(None), SubjectFee.effective_to >= target),
            SubjectFee.is_active.is_(True),
        )
        .order_by(SubjectFee.effective_from.desc(), SubjectFee.id.desc())
        .first()
    )


def list_subject_fees(user, subject_id=None, history=False, search=None, status=None):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403
    query = SubjectFee.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)
    if subject_id:
        query = query.filter_by(subject_id=int(subject_id))
    if search:
        query = query.join(Subject).filter(func.lower(Subject.name).like(f"%{str(search).strip().lower()}%"))
    if status and str(status).lower() != "all":
        query = query.filter(SubjectFee.is_active.is_(str(status).lower() == "active"))
    if not history:
        today = local_today()
        query = query.filter(
            SubjectFee.effective_from <= today,
            or_(SubjectFee.effective_to.is_(None), SubjectFee.effective_to >= today),
            SubjectFee.is_active.is_(True),
        )
    rows = query.order_by(SubjectFee.subject_id.asc(), SubjectFee.effective_from.desc()).all()
    return {"subject_fees": [row.to_dict() for row in rows]}, 200


def configure_subject_fee(subject_id, data, user):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    subject = Subject.query.filter_by(id=subject_id, institution_id=user.institution_id).first()
    if not subject:
        return {"errors": ["Subject not found"]}, 404
    amount = _decimal(data.get("monthly_fee", data.get("monthlyFee")))
    if amount is None or amount < ZERO:
        return {"errors": ["monthly_fee must be zero or greater"]}, 400
    effective = _parse_date(data.get("effective_from", data.get("effectiveFrom")), local_today().replace(day=1))
    if not effective:
        return {"errors": ["effective_from must be a valid date"]}, 400
    effective = effective.replace(day=1)
    if SubjectFee.query.filter_by(
        institution_id=user.institution_id, subject_id=subject.id, effective_from=effective
    ).first():
        return {"errors": ["A fee already starts in this month"]}, 409

    previous = (
        SubjectFee.query.filter(
            SubjectFee.institution_id == user.institution_id,
            SubjectFee.subject_id == subject.id,
            SubjectFee.effective_from < effective,
        ).order_by(SubjectFee.effective_from.desc()).first()
    )
    following = (
        SubjectFee.query.filter(
            SubjectFee.institution_id == user.institution_id,
            SubjectFee.subject_id == subject.id,
            SubjectFee.effective_from > effective,
        ).order_by(SubjectFee.effective_from.asc()).first()
    )
    row = SubjectFee(
        institution_id=user.institution_id,
        subject_id=subject.id,
        monthly_fee=amount,
        currency=str(data.get("currency") or "LKR").upper()[:3],
        effective_from=effective,
        effective_to=(following.effective_from - timedelta(days=1)) if following else None,
        is_active=bool(data.get("is_active", data.get("isActive", True))),
        description=(data.get("description") or "").strip() or None,
        created_by=user.id,
    )
    if previous and (previous.effective_to is None or previous.effective_to >= effective):
        previous.effective_to = effective - timedelta(days=1)
    db.session.add(row)
    try:
        db.session.flush()
        _audit(user, "SUBJECT_FEE_CREATED", "subject_fee", row.id, {"amount": str(amount), "effective_from": effective.isoformat()})
        db.session.commit()
        return {"subject_fee": row.to_dict()}, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to configure subject fee"]}, 500


def update_subject_fee(fee_id, data, user):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    fee = SubjectFee.query.filter_by(id=fee_id, institution_id=user.institution_id).first()
    if not fee:
        return {"errors": ["Subject fee not found"]}, 404
    used = InvoiceLineItem.query.filter_by(
        institution_id=user.institution_id, subject_id=fee.subject_id
    ).first() is not None
    amount_raw = data.get("monthly_fee", data.get("monthlyFee"))
    amount = _decimal(amount_raw, default=Decimal(fee.monthly_fee))
    effective = _parse_date(
        data.get("effective_from", data.get("effectiveFrom")), fee.effective_from
    )
    if amount is None or amount < ZERO or not effective:
        return {"errors": ["Invalid monthly fee or effective date"]}, 400
    effective = effective.replace(day=1)
    if used and (amount != Decimal(fee.monthly_fee) or effective != fee.effective_from):
        return configure_subject_fee(fee.subject_id, {
            "monthly_fee": str(amount),
            "currency": data.get("currency", fee.currency),
            "effective_from": effective.isoformat(),
            "is_active": data.get("is_active", data.get("isActive", True)),
            "description": data.get("description", fee.description),
        }, user)
    fee.monthly_fee = amount
    fee.currency = str(data.get("currency") or fee.currency).upper()[:3]
    fee.effective_from = effective
    if "is_active" in data or "isActive" in data:
        fee.is_active = bool(data.get("is_active", data.get("isActive")))
    if "description" in data:
        fee.description = str(data.get("description") or "").strip() or None
    _audit(user, "SUBJECT_FEE_UPDATED", "subject_fee", fee.id, {"amount": str(amount)})
    try:
        db.session.commit()
        return {"subject_fee": fee.to_dict(), "historical_version_created": False}, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to update subject fee"]}, 500


def delete_subject_fee(fee_id, user):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    fee = SubjectFee.query.filter_by(id=fee_id, institution_id=user.institution_id).first()
    if not fee:
        return {"errors": ["Subject fee not found"]}, 404
    used = InvoiceLineItem.query.filter_by(
        institution_id=user.institution_id, subject_id=fee.subject_id
    ).first() is not None
    if used:
        fee.is_active = False
        if fee.effective_to is None or fee.effective_to > local_today():
            fee.effective_to = local_today()
        _audit(user, "SUBJECT_FEE_DEACTIVATED", "subject_fee", fee.id)
        db.session.commit()
        return {"subject_fee": fee.to_dict(), "deleted": False, "deactivated": True}, 200
    payload = fee.to_dict()
    _audit(user, "SUBJECT_FEE_DELETED", "subject_fee", fee.id)
    db.session.delete(fee)
    db.session.commit()
    return {"subject_fee": payload, "deleted": True, "deactivated": False}, 200


def fee_preview(subject_names, institution_id, joining_date=None, discount=ZERO):
    target = joining_date or local_today()
    names = {str(name).strip().lower() for name in (subject_names or []) if str(name).strip()}
    subjects = Subject.query.filter_by(institution_id=institution_id).all()
    matched = [subject for subject in subjects if subject.name.strip().lower() in names]
    lines = []
    total = ZERO
    for subject in matched:
        fee = current_subject_fee(subject.id, institution_id, target)
        amount = Decimal(fee.monthly_fee) if fee else None
        if amount is not None:
            total += amount
        lines.append({
            "subject_id": subject.id,
            "subject_name": subject.name,
            "monthly_fee": float(amount) if amount is not None else None,
            "currency": fee.currency if fee else "LKR",
            "configured": fee is not None,
        })
    discount = max(ZERO, discount or ZERO)
    return {
        "joining_month": target.strftime("%Y-%m"),
        "lines": lines,
        "monthly_fee": float(total),
        "discount": float(discount),
        "net_monthly_fee": float(max(ZERO, total - discount)),
        "missing_subjects": sorted(names - {subject.name.strip().lower() for subject in matched}),
    }


def preview_registration_fees(data, user):
    if user.role not in ("institution_admin", "teacher"):
        return {"errors": ["Access denied"]}, 403
    joining = _parse_date(data.get("joining_date", data.get("joiningDate")), local_today())
    discount = _decimal(data.get("discount", data.get("discount_amount", 0)), default=ZERO)
    if not joining or discount is None or discount < ZERO:
        return {"errors": ["Invalid joining date or discount"]}, 400
    return fee_preview(data.get("subjects") or data.get("enrolledSubjects") or [], user.institution_id, joining, discount), 200


def add_enrollment_snapshots(student, subject_names, user, joining_date=None, discount=ZERO):
    start = joining_date or local_today()
    names = {str(name).strip().lower() for name in subject_names or []}
    subjects = Subject.query.filter_by(institution_id=student.institution_id).all()
    remaining_discount = max(ZERO, discount or ZERO)
    for subject in sorted(subjects, key=lambda item: item.id):
        if subject.name.strip().lower() not in names:
            continue
        fee = current_subject_fee(subject.id, student.institution_id, start)
        fee_amount = Decimal(fee.monthly_fee) if fee else ZERO
        subject_discount = min(fee_amount, remaining_discount)
        remaining_discount -= subject_discount
        db.session.add(StudentSubjectEnrollment(
            institution_id=student.institution_id,
            student_id=student.id,
            subject_id=subject.id,
            start_date=start,
            fee_snapshot=fee.monthly_fee if fee else None,
            discount_amount=subject_discount,
            is_active=True,
        ))


def sync_student_enrollments(student, subject_names, user, joining_date=None, discount=ZERO):
    start = joining_date or local_today()
    requested = {str(name).strip().lower() for name in subject_names or [] if str(name).strip()}
    active = StudentSubjectEnrollment.query.filter_by(
        institution_id=student.institution_id, student_id=student.id, is_active=True
    ).all()
    active_names = {row.subject.name.strip().lower(): row for row in active if row.subject}
    for name, enrollment in active_names.items():
        if name not in requested:
            enrollment.is_active = False
            enrollment.end_date = start - timedelta(days=1)
    missing = requested - set(active_names)
    if missing:
        add_enrollment_snapshots(student, missing, user, start, discount)


def _credit_balance(student_id, institution_id):
    value = db.session.query(func.coalesce(func.sum(AdvanceCreditLedger.amount), 0)).filter_by(
        student_id=student_id, institution_id=institution_id
    ).scalar()
    return Decimal(value or 0)


def _refresh_invoice(invoice):
    paid = sum((Decimal(line.paid_amount or 0) for line in invoice.lines), ZERO)
    net = Decimal(invoice.net_total or 0)
    invoice.paid_amount = paid
    invoice.balance_due = max(ZERO, net - paid - Decimal(invoice.applied_credit or 0))
    if invoice.status == "CANCELLED":
        return
    if net == ZERO and Decimal(invoice.waived_amount or 0) > ZERO:
        invoice.status = "WAIVED"
    elif invoice.balance_due == ZERO:
        invoice.status = "PAID"
    elif paid > ZERO or Decimal(invoice.applied_credit or 0) > ZERO:
        invoice.status = "PARTIALLY_PAID"
    else:
        invoice.status = "UNPAID"


def generate_invoice(student_id, period, user):
    student, error = _tenant_student(student_id, user)
    if error:
        return error
    period = _period(period)
    if not period:
        return {"errors": ["billing_period must be YYYY-MM"]}, 400
    existing = MonthlyInvoice.query.filter_by(
        institution_id=student.institution_id, student_id=student.id, billing_period=period
    ).first()
    if existing:
        return {"invoice": existing.to_dict(), "created": False}, 200

    start, end = _period_start(period), _period_end(period)
    enrollments = StudentSubjectEnrollment.query.filter(
        StudentSubjectEnrollment.institution_id == student.institution_id,
        StudentSubjectEnrollment.student_id == student.id,
        StudentSubjectEnrollment.start_date <= end,
        or_(StudentSubjectEnrollment.end_date.is_(None), StudentSubjectEnrollment.end_date >= start),
        StudentSubjectEnrollment.is_active.is_(True),
    ).all()
    previous = db.session.query(func.coalesce(func.sum(MonthlyInvoice.balance_due), 0)).filter(
        MonthlyInvoice.institution_id == student.institution_id,
        MonthlyInvoice.student_id == student.id,
        MonthlyInvoice.billing_period < period,
        MonthlyInvoice.status.notin_(("CANCELLED", "REFUNDED")),
    ).scalar()
    invoice = MonthlyInvoice(
        institution_id=student.institution_id,
        student_id=student.id,
        billing_period=period,
        previous_balance=Decimal(previous or 0),
        created_by=user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    charges = discounts = ZERO
    for enrollment in enrollments:
        fee = current_subject_fee(enrollment.subject_id, student.institution_id, start)
        amount = Decimal(fee.monthly_fee) if fee else Decimal(enrollment.fee_snapshot or 0)
        discount = min(amount, Decimal(enrollment.discount_amount or 0))
        net = amount - discount
        charges += amount
        discounts += discount
        db.session.add(InvoiceLineItem(
            invoice_id=invoice.id,
            institution_id=student.institution_id,
            enrollment_id=enrollment.id,
            subject_id=enrollment.subject_id,
            subject_name=enrollment.subject.name,
            fee_amount=amount,
            discount_amount=discount,
            net_amount=net,
        ))
    invoice.subject_charges = charges
    invoice.discount_amount = discounts
    invoice.net_total = max(ZERO, charges - discounts - Decimal(invoice.waived_amount or 0))
    available_credit = max(ZERO, _credit_balance(student.id, student.institution_id))
    applied = min(available_credit, Decimal(invoice.net_total))
    invoice.applied_credit = applied
    if applied:
        db.session.add(AdvanceCreditLedger(
            institution_id=student.institution_id, student_id=student.id, invoice_id=invoice.id,
            entry_type="APPLIED", amount=-applied, notes=f"Applied to {period}", created_by=user.id,
        ))
        _audit(user, "ADVANCE_CREDIT_APPLIED", "invoice", invoice.id, {"amount": str(applied)})
    db.session.flush()
    _refresh_invoice(invoice)
    _audit(user, "INVOICE_CREATED", "invoice", invoice.id, {"billing_period": period})
    try:
        db.session.commit()
        return {"invoice": invoice.to_dict(), "created": True}, 201
    except Exception:
        db.session.rollback()
        existing = MonthlyInvoice.query.filter_by(
            institution_id=student.institution_id, student_id=student.id, billing_period=period
        ).first()
        if existing:
            return {"invoice": existing.to_dict(), "created": False}, 200
        return {"errors": ["Failed to generate invoice"]}, 500


def generate_institution_invoices(user, period=None):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    period = _period(period)
    if not period:
        return {"errors": ["billing_period must be YYYY-MM"]}, 400
    students = Student.query.join(Student.user).filter(
        Student.institution_id == user.institution_id,
        Student.user.has(is_active=True),
    ).all()
    created = existing = failed = 0
    for student in students:
        result, status = generate_invoice(student.id, period, user)
        if status == 201:
            created += 1
        elif status == 200:
            existing += 1
        else:
            failed += 1
    return {"billing_period": period, "created": created, "existing": existing, "failed": failed}, 200


def list_invoices(user, student_id=None, period=None, status=None):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403
    query = MonthlyInvoice.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)
    if student_id:
        query = query.filter_by(student_id=int(student_id))
    if period:
        query = query.filter_by(billing_period=period)
    if status:
        query = query.filter_by(status=str(status).upper())
    rows = query.order_by(MonthlyInvoice.billing_period.desc(), MonthlyInvoice.id.desc()).all()
    return {"invoices": [row.to_dict() for row in rows]}, 200


def _allocate_to_line(payment, invoice, line, amount):
    remaining = max(ZERO, Decimal(line.net_amount or 0) - Decimal(line.paid_amount or 0))
    allocated = min(remaining, amount)
    if allocated <= ZERO:
        return ZERO
    line.paid_amount = Decimal(line.paid_amount or 0) + allocated
    line.status = "PAID" if line.paid_amount >= line.net_amount else "PARTIALLY_PAID"
    db.session.add(PaymentAllocation(
        institution_id=payment.institution_id, payment_id=payment.id, invoice_id=invoice.id,
        invoice_line_id=line.id, amount=allocated,
    ))
    return allocated


def record_tuition_payment(data, user, idempotency_key=None):
    if user.role not in ("institution_admin", "teacher"):
        return {"errors": ["Access denied"]}, 403
    student_id = data.get("student_id", data.get("studentId"))
    student, error = _tenant_student(student_id, user)
    if error:
        return error
    key = str(idempotency_key or data.get("idempotency_key") or data.get("idempotencyKey") or "").strip()
    if not key:
        return {"errors": ["Idempotency-Key is required"]}, 400
    existing = TuitionPayment.query.filter_by(institution_id=user.institution_id, idempotency_key=key).first()
    if existing:
        return {"payment": existing.to_dict(), "created": False}, 200
    amount = _decimal(data.get("amount"))
    if amount is None or amount <= ZERO:
        return {"errors": ["amount must be greater than zero"]}, 400
    method = str(data.get("payment_method", data.get("paymentMethod", "CASH"))).upper()
    if method not in VALID_PAYMENT_METHODS:
        return {"errors": ["Invalid payment method"]}, 400
    payment_date = _parse_date(data.get("payment_date", data.get("paymentDate")), local_today())
    if not payment_date:
        return {"errors": ["Invalid payment date"]}, 400
    subject_id = data.get("subject_id", data.get("subjectId"))
    if subject_id:
        subject = Subject.query.filter_by(id=int(subject_id), institution_id=user.institution_id).first()
        if not subject:
            return {"errors": ["Subject not found"]}, 404
        subject_id = subject.id
    raw_period = data.get("billing_period", data.get("billingPeriod"))
    requested_period = _period(raw_period) if raw_period else None
    if raw_period and not requested_period:
        return {"errors": ["billing_period must be YYYY-MM"]}, 400
    invoice_id = data.get("invoice_id", data.get("invoiceId"))
    payment = TuitionPayment(
        institution_id=user.institution_id, student_id=student.id, invoice_id=int(invoice_id) if invoice_id else None,
        billing_period=requested_period, subject_id=subject_id, amount=amount, payment_method=method,
        reference_number=(data.get("reference_number", data.get("referenceNumber")) or "").strip() or None,
        payment_date=payment_date, notes=(data.get("notes") or "").strip() or None,
        recorded_by=user.id, status="COMPLETED", idempotency_key=key,
    )
    db.session.add(payment)
    db.session.flush()
    invoice_query = MonthlyInvoice.query.filter(
        MonthlyInvoice.institution_id == user.institution_id,
        MonthlyInvoice.student_id == student.id,
        MonthlyInvoice.balance_due > ZERO,
        MonthlyInvoice.status.notin_(("CANCELLED", "REFUNDED")),
    )
    if invoice_id:
        invoice_query = invoice_query.filter(MonthlyInvoice.id == int(invoice_id))
    elif requested_period:
        invoice_query = invoice_query.filter(MonthlyInvoice.billing_period == requested_period)
    invoices = invoice_query.order_by(MonthlyInvoice.billing_period.asc(), MonthlyInvoice.id.asc()).all()
    if invoices:
        payment.invoice_id = invoices[0].id
        payment.billing_period = invoices[0].billing_period
    remaining = amount
    for invoice in invoices:
        lines = sorted(invoice.lines, key=lambda line: line.id)
        if subject_id:
            lines = [line for line in lines if line.subject_id == subject_id]
        for line in lines:
            allocated = _allocate_to_line(payment, invoice, line, remaining)
            remaining -= allocated
            if remaining <= ZERO:
                break
        _refresh_invoice(invoice)
        if remaining <= ZERO:
            break
    if remaining > ZERO:
        db.session.add(AdvanceCreditLedger(
            institution_id=user.institution_id, student_id=student.id, payment_id=payment.id,
            entry_type="CREATED", amount=remaining, notes="Payment overage", created_by=user.id,
        ))
        _audit(user, "ADVANCE_CREDIT_CREATED", "payment", payment.id, {"amount": str(remaining)})
        if invoices:
            invoices[-1].status = "OVERPAID"
    payment.receipt_number = f"{local_today():%Y%m%d}-{user.institution_id:04d}-{payment.id:07d}"
    db.session.flush()
    institution = db.session.get(Institution, user.institution_id)
    allocated_subjects = []
    for allocation in payment.allocations:
        line = db.session.get(InvoiceLineItem, allocation.invoice_line_id) if allocation.invoice_line_id else None
        allocated_subjects.append({
            "subject": line.subject_name if line else None,
            "amount": float(allocation.amount),
            "billing_period": db.session.get(MonthlyInvoice, allocation.invoice_id).billing_period,
        })
    remaining_balance = db.session.query(func.coalesce(func.sum(MonthlyInvoice.balance_due), 0)).filter(
        MonthlyInvoice.institution_id == user.institution_id,
        MonthlyInvoice.student_id == student.id,
        MonthlyInvoice.status.notin_(("CANCELLED", "REFUNDED")),
    ).scalar()
    snapshot = {
        "institution": institution.to_dict() if institution else None,
        "student_name": student.user.full_name if student.user else None,
        "registration_no": student.registration_no,
        "grade": student.grade,
        "amount_paid": float(amount),
        "payment_method": method,
        "payment_date": payment_date.isoformat(),
        "recorded_by": user.full_name,
        "advance_credit": float(remaining),
        "subjects": allocated_subjects,
        "remaining_balance": float(Decimal(remaining_balance or 0)),
    }
    receipt = FeeReceipt(
        institution_id=user.institution_id, payment_id=payment.id,
        receipt_number=payment.receipt_number, snapshot=snapshot,
    )
    db.session.add(receipt)
    _audit(user, "PAYMENT_RECORDED", "payment", payment.id, {"amount": str(amount), "method": method})
    try:
        db.session.commit()
        return {"payment": payment.to_dict(), "receipt": receipt.to_dict(), "created": True}, 201
    except Exception:
        db.session.rollback()
        existing = TuitionPayment.query.filter_by(institution_id=user.institution_id, idempotency_key=key).first()
        if existing:
            return {"payment": existing.to_dict(), "created": False}, 200
        return {"errors": ["Failed to record payment"]}, 500


def change_payment_status(payment_id, data, user):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    payment = TuitionPayment.query.filter_by(id=payment_id, institution_id=user.institution_id).first()
    if not payment:
        return {"errors": ["Payment not found"]}, 404
    target = str(data.get("status") or "").upper()
    if target not in ("CANCELLED", "REVERSED", "REFUNDED"):
        return {"errors": ["status must be CANCELLED, REVERSED, or REFUNDED"]}, 400
    if payment.status not in ACTIVE_PAYMENT_STATUSES:
        return {"errors": ["Payment is already inactive"]}, 409
    for allocation in payment.allocations:
        line = db.session.get(InvoiceLineItem, allocation.invoice_line_id) if allocation.invoice_line_id else None
        if line:
            line.paid_amount = max(ZERO, Decimal(line.paid_amount or 0) - Decimal(allocation.amount))
            line.status = "UNPAID" if line.paid_amount == ZERO else "PARTIALLY_PAID"
        invoice = db.session.get(MonthlyInvoice, allocation.invoice_id)
        if invoice:
            _refresh_invoice(invoice)
    credits = AdvanceCreditLedger.query.filter_by(payment_id=payment.id, entry_type="CREATED").all()
    for credit in credits:
        db.session.add(AdvanceCreditLedger(
            institution_id=payment.institution_id, student_id=payment.student_id, payment_id=payment.id,
            entry_type=target, amount=-Decimal(credit.amount), notes=f"Credit removed by {target.lower()}", created_by=user.id,
        ))
    payment.status = target
    _audit(user, f"PAYMENT_{target}", "payment", payment.id, {"reason": data.get("reason")})
    db.session.commit()
    return {"payment": payment.to_dict()}, 200


def list_tuition_payments(user, student_id=None, period=None, method=None, recorded_by=None):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403
    query = TuitionPayment.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)
    if student_id:
        query = query.filter_by(student_id=int(student_id))
    if period:
        query = query.filter_by(billing_period=period)
    if method:
        query = query.filter_by(payment_method=method.upper())
    if recorded_by:
        query = query.filter_by(recorded_by=int(recorded_by))
    rows = query.order_by(TuitionPayment.payment_date.desc(), TuitionPayment.id.desc()).all()
    return {"payments": [row.to_dict() for row in rows]}, 200


def get_receipt(receipt_id, user):
    query = FeeReceipt.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)
    receipt = query.filter(or_(FeeReceipt.id == receipt_id, FeeReceipt.payment_id == receipt_id)).first()
    if not receipt:
        return {"errors": ["Receipt not found"]}, 404
    if user.role == "parent" and receipt.payment.student.parent_id != user.id:
        return {"errors": ["Receipt not found"]}, 404
    if receipt.payment.status != "COMPLETED":
        return {"errors": ["Receipt unavailable for inactive payment"]}, 409
    return {"receipt": receipt.to_dict()}, 200


def receipt_pdf(receipt_id, user):
    result, status = get_receipt(receipt_id, user)
    if status != 200:
        return result, status
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    receipt = result["receipt"]
    snapshot = receipt["snapshot"]
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A4)
    width, height = A4
    y = height - 56
    institution = snapshot.get("institution") or {}
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(48, y, institution.get("name") or "Tuition Fee Receipt")
    y -= 28
    pdf.setFont("Helvetica", 10)
    rows = [
        ("Receipt number", receipt["receipt_number"]),
        ("Student", snapshot.get("student_name")),
        ("Student ID", snapshot.get("registration_no")),
        ("Grade/Class", snapshot.get("grade")),
        ("Amount paid", f"LKR {snapshot.get('amount_paid', 0):,.2f}"),
        ("Payment method", snapshot.get("payment_method")),
        ("Payment date", snapshot.get("payment_date")),
        ("Recorded by", snapshot.get("recorded_by")),
        ("Remaining balance", f"LKR {snapshot.get('remaining_balance', 0):,.2f}"),
        ("Advance credit", f"LKR {snapshot.get('advance_credit', 0):,.2f}"),
    ]
    for label, value in rows:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(48, y, f"{label}:")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(170, y, str(value or "—"))
        y -= 18
    subjects = snapshot.get("subjects") or []
    if subjects:
        y -= 8
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(48, y, "Allocated subjects")
        y -= 18
        for item in subjects:
            pdf.setFont("Helvetica", 10)
            pdf.drawString(58, y, f"{item.get('subject') or 'General'} · {item.get('billing_period')} · LKR {item.get('amount', 0):,.2f}")
            y -= 16
    pdf.showPage()
    pdf.save()
    stream.seek(0)
    return {"content": stream.read(), "filename": f"receipt_{receipt['receipt_number']}.pdf"}, 200


def run_scheduled_invoice_generation():
    period = _period()
    admins = User.query.filter_by(role="institution_admin", is_active=True).all()
    for admin in admins:
        try:
            generate_institution_invoices(admin, period)
        except Exception:
            db.session.rollback()


def adjust_invoice(invoice_id, data, user):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    invoice = MonthlyInvoice.query.filter_by(id=invoice_id, institution_id=user.institution_id).first()
    if not invoice:
        return {"errors": ["Invoice not found"]}, 404
    discount = _decimal(data.get("discount_amount", data.get("discountAmount")), default=Decimal(invoice.discount_amount or 0))
    waived = _decimal(data.get("waived_amount", data.get("waivedAmount")), default=Decimal(invoice.waived_amount or 0))
    if discount is None or waived is None or discount < ZERO or waived < ZERO:
        return {"errors": ["Discount and waived amount must be zero or greater"]}, 400
    invoice.discount_amount = discount
    invoice.waived_amount = waived
    invoice.notes = (data.get("notes") or invoice.notes or "").strip() or None
    invoice.net_total = max(ZERO, Decimal(invoice.subject_charges or 0) - discount - waived)
    _refresh_invoice(invoice)
    _audit(user, "INVOICE_ADJUSTED", "invoice", invoice.id, {"discount": str(discount), "waived": str(waived)})
    db.session.commit()
    return {"invoice": invoice.to_dict()}, 200


def list_credit_ledger(user, student_id=None):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403
    query = AdvanceCreditLedger.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)
    if student_id:
        query = query.filter_by(student_id=int(student_id))
    rows = query.order_by(AdvanceCreditLedger.created_at.desc(), AdvanceCreditLedger.id.desc()).all()
    return {"credits": [{
        "id": row.id, "student_id": row.student_id, "payment_id": row.payment_id,
        "invoice_id": row.invoice_id, "entry_type": row.entry_type, "amount": float(row.amount),
        "notes": row.notes, "created_at": row.created_at.isoformat(),
    } for row in rows]}, 200


def list_financial_audit(user):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    rows = FinancialAuditLog.query.filter_by(institution_id=user.institution_id).order_by(
        FinancialAuditLog.created_at.desc(), FinancialAuditLog.id.desc()
    ).limit(500).all()
    return {"audit_logs": [{
        "id": row.id, "actor_id": row.actor_id, "action": row.action,
        "entity_type": row.entity_type, "entity_id": row.entity_id,
        "details": row.details, "created_at": row.created_at.isoformat(),
    } for row in rows]}, 200


def student_fee_summary(student_id, user, period=None, allow_parent=False):
    student, error = _tenant_student(student_id, user, allow_parent=allow_parent)
    if error:
        return error
    period = _period(period)
    invoice = MonthlyInvoice.query.filter_by(
        institution_id=student.institution_id, student_id=student.id, billing_period=period
    ).first()
    if invoice:
        credit_remaining = Decimal(invoice.applied_credit or 0)
        subject_rows = []
        for line in sorted(invoice.lines, key=lambda item: item.id):
            expected = Decimal(line.net_amount or 0)
            direct_paid = Decimal(line.paid_amount or 0)
            credit_for_line = min(credit_remaining, max(ZERO, expected - direct_paid))
            credit_remaining -= credit_for_line
            paid = direct_paid + credit_for_line
            balance = max(ZERO, expected - paid)
            status = "PAID" if balance == ZERO else "PARTIALLY_PAID" if paid > ZERO else "UNPAID"
            subject_rows.append({
                "subject_id": line.subject_id,
                "subject_name": line.subject_name,
                "expected_fee": float(expected),
                "fee_amount": float(expected),
                "paid_amount": float(paid),
                "balance": float(balance),
                "balance_due": float(balance),
                "status": status,
            })
        total_paid = Decimal(invoice.paid_amount or 0) + Decimal(invoice.applied_credit or 0)
        if Decimal(invoice.balance_due or 0) == ZERO and subject_rows:
            overall_status = "PAID"
        elif total_paid > ZERO:
            overall_status = "PARTIALLY_PAID"
        else:
            overall_status = "UNPAID"
        payload = invoice.to_dict(include_lines=False)
        payload.update({
            "student_name": student.user.full_name if student.user else None,
            "billing_month": period,
            "overall_status": overall_status,
            "total_fee": float(Decimal(invoice.net_total or 0)),
            "total_paid": float(total_paid),
            "total_pending": float(Decimal(invoice.balance_due or 0)),
            "paid_subject_count": sum(1 for row in subject_rows if row["status"] == "PAID"),
            "pending_subject_count": sum(1 for row in subject_rows if row["status"] != "PAID"),
            "advance_credit": float(max(ZERO, _credit_balance(student.id, student.institution_id))),
            "subjects": subject_rows,
            "lines": subject_rows,
            "legacy": False,
        })
        return {"fee_summary": payload}, 200
    legacy = StudentPayment.query.filter_by(student_id=student.id, billing_period=period).first()
    paid = legacy is not None and legacy.payment_status == "Paid"
    amount = float(legacy.amount or legacy.amount_due or 0) if legacy else 0
    return {"fee_summary": {
        "student_id": student.id, "billing_period": period,
        "student_name": student.user.full_name if student.user else None,
        "billing_month": period,
        "overall_status": "PAID" if paid else "UNPAID",
        "subject_charges": amount, "net_total": amount,
        "paid_amount": amount if paid else 0, "balance_due": 0 if paid else amount,
        "total_fee": amount, "total_paid": amount if paid else 0,
        "total_pending": 0 if paid else amount,
        "paid_subject_count": 0, "pending_subject_count": 0,
        "advance_credit": float(max(ZERO, _credit_balance(student.id, student.institution_id))),
        "subjects": [], "lines": [], "legacy": True, "legacy_message": "Legacy payment record; subject breakdown unavailable.",
    }}, 200


def student_fee_history(student_id, user):
    student, error = _tenant_student(student_id, user, allow_parent=True)
    if error:
        return error
    invoices = MonthlyInvoice.query.filter_by(
        institution_id=student.institution_id, student_id=student.id
    ).order_by(MonthlyInvoice.billing_period.desc()).all()
    payments = TuitionPayment.query.filter_by(
        institution_id=student.institution_id, student_id=student.id
    ).order_by(TuitionPayment.payment_date.desc(), TuitionPayment.id.desc()).all()
    return {
        "student": student.to_dict(),
        "invoices": [invoice.to_dict() for invoice in invoices],
        "payments": [payment.to_dict() for payment in payments],
        "advance_credit": float(max(ZERO, _credit_balance(student.id, student.institution_id))),
    }, 200


def billing_dashboard(user, period=None):
    if user.role != "institution_admin":
        return {"errors": ["Access denied"]}, 403
    period = _period(period)
    invoices = MonthlyInvoice.query.filter_by(institution_id=user.institution_id, billing_period=period).all()
    expected = sum((Decimal(item.net_total or 0) for item in invoices), ZERO)
    collected = sum((Decimal(item.paid_amount or 0) + Decimal(item.applied_credit or 0) for item in invoices), ZERO)
    pending = sum((Decimal(item.balance_due or 0) for item in invoices), ZERO)
    credits = db.session.query(func.coalesce(func.sum(AdvanceCreditLedger.amount), 0)).filter_by(institution_id=user.institution_id).scalar()
    return {"summary": {
        "billing_period": period, "expected_fees": float(expected), "total_collected": float(collected),
        "total_pending": float(pending), "total_advance_credit": float(Decimal(credits or 0)),
        "paid_students": sum(1 for item in invoices if item.balance_due == ZERO),
        "pending_students": sum(1 for item in invoices if item.balance_due > ZERO),
    }}, 200
