from calendar import month_name
from datetime import date, datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Student, StudentPayment, User
from app.models.student_payment_model import (
    billing_period_from_month_year,
    month_label,
    month_year_from_billing_period,
)
from app.utils import local_today, utc_now


def _authorize_student(student, user):
    if not student:
        return {"errors": ["Student not found"]}, 404
    if user.role == "super_admin":
        return None
    if user.role in ("institution_admin", "teacher"):
        if student.institution_id != user.institution_id:
            return {"errors": ["Access denied"]}, 403
        return None
    return {"errors": ["Access denied"]}, 403


def _parse_month(raw):
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    if text.isdigit():
        value = int(text)
        if 1 <= value <= 12:
            return value
        return None
    for index in range(1, 13):
        if text.lower() == month_name[index].lower() or text.lower() == month_name[index][:3].lower():
            return index
    return None


def _parse_year(raw):
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if 2000 <= value <= 2100:
        return value
    return None


def _parse_amount(raw):
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_payment_date(raw):
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_status(raw):
    status = str(raw or "").strip().title()
    if status in ("Paid", "Pending"):
        return status
    if status == "Overdue":
        return "Pending"
    return None


def _enrich_payment_dict(payment: StudentPayment):
    payload = payment.to_dict()
    student = payment.student
    if student is not None:
        payload["student_name"] = student.user.full_name if student.user else None
        payload["studentName"] = payload["student_name"]
        payload["registration_no"] = student.registration_no
        payload["registrationNo"] = student.registration_no
        payload["grade"] = student.grade
    return payload


def _current_period():
    today = local_today()
    return today.month, today.year, billing_period_from_month_year(today.month, today.year)


def get_or_build_current_payment_payload(student_id: int):
    """Return current-month payment dict (synthetic Pending if none exists)."""
    month, year, period = _current_period()
    payment = StudentPayment.query.filter_by(student_id=student_id, billing_period=period).first()
    if payment:
        return payment.to_dict(), payment
    return {
        "id": None,
        "student_id": student_id,
        "studentId": student_id,
        "month": month,
        "year": year,
        "month_name": month_label(month),
        "monthName": month_label(month),
        "amount": None,
        "amount_due": None,
        "amountDue": None,
        "payment_status": "Pending",
        "paymentStatus": "Pending",
        "payment_date": None,
        "paymentDate": None,
        "billing_period": period,
        "billingPeriod": period,
        "paid_at": None,
        "paidAt": None,
        "created_at": None,
        "createdAt": None,
        "updated_at": None,
        "updatedAt": None,
        "exists": False,
    }, None


def list_payments(user, *, month=None, year=None, status=None, search=None, student_id=None):
    if user.role not in ("institution_admin", "super_admin", "teacher"):
        return {"errors": ["Access denied"]}, 403

    query = StudentPayment.query.join(Student).options(
        joinedload(StudentPayment.student).joinedload(Student.user)
    )
    if user.role != "super_admin":
        query = query.filter(Student.institution_id == user.institution_id)

    if student_id is not None:
        query = query.filter(StudentPayment.student_id == int(student_id))

    month_value = _parse_month(month)
    year_value = _parse_year(year)
    if month_value:
        query = query.filter(
            or_(
                StudentPayment.month == month_value,
                StudentPayment.billing_period.like(f"%-{month_value:02d}"),
            )
        )
    if year_value:
        query = query.filter(
            or_(
                StudentPayment.year == year_value,
                StudentPayment.billing_period.like(f"{year_value}-%"),
            )
        )

    status_value = _parse_status(status) if status else None
    if status and str(status).strip().lower() not in ("all", ""):
        if not status_value:
            return {"errors": ["payment_status must be Paid or Pending"]}, 400
        query = query.filter(StudentPayment.payment_status == status_value)

    search_text = (search or "").strip()
    if search_text:
        pattern = f"%{search_text.lower()}%"
        query = query.join(User, Student.user_id == User.id).filter(
            or_(
                func.lower(User.full_name).like(pattern),
                func.lower(Student.registration_no).like(pattern),
            )
        )

    rows = query.order_by(
        StudentPayment.year.desc(),
        StudentPayment.month.desc(),
        StudentPayment.id.desc(),
    ).all()

    return {
        "payments": [_enrich_payment_dict(row) for row in rows],
        "count": len(rows),
    }, 200


def create_payment(data, user):
    if user.role not in ("institution_admin", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student_id = data.get("student_id") or data.get("studentId")
    if student_id is None:
        return {"errors": ["student_id is required"]}, 400

    student = Student.query.get(int(student_id))
    denied = _authorize_student(student, user)
    if denied:
        return denied

    month = _parse_month(data.get("month"))
    year = _parse_year(data.get("year"))
    period = str(data.get("billing_period") or data.get("billingPeriod") or "").strip()

    if (month is None or year is None) and period:
        month, year = month_year_from_billing_period(period)
    if month is None or year is None:
        today = local_today()
        month = month or today.month
        year = year or today.year

    if month is None or year is None:
        return {"errors": ["month and year are required"]}, 400

    period = billing_period_from_month_year(month, year)
    amount = _parse_amount(data.get("amount") if data.get("amount") is not None else data.get("amount_due"))
    if amount is None:
        return {"errors": ["amount is required"]}, 400
    if amount < 0:
        return {"errors": ["amount must be zero or greater"]}, 400

    status = _parse_status(data.get("payment_status") or data.get("paymentStatus") or "Pending")
    if not status:
        return {"errors": ["payment_status must be Paid or Pending"]}, 400

    payment_date = _parse_payment_date(data.get("payment_date") or data.get("paymentDate"))
    if status == "Paid" and payment_date is None:
        payment_date = local_today()
    if status != "Paid":
        payment_date = None

    existing = StudentPayment.query.filter_by(student_id=student.id, billing_period=period).first()
    if existing:
        return {
            "errors": [
                f"Payment already exists for {month_label(month)} {year}. Update the existing record instead."
            ],
            "payment": _enrich_payment_dict(existing),
        }, 409

    payment = StudentPayment(
        student_id=student.id,
        month=month,
        year=year,
        amount=amount,
        amount_due=amount,
        payment_status=status,
        payment_date=payment_date if status == "Paid" else None,
        billing_period=period,
        paid_at=datetime.combine(payment_date, datetime.min.time()) if status == "Paid" and payment_date else None,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    payment.sync_period_fields()
    db.session.add(payment)

    try:
        db.session.commit()
        db.session.refresh(payment)
        return {"success": True, "payment": _enrich_payment_dict(payment)}, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to create payment record"]}, 500


def get_student_payment_history(student_id, user):
    if user.role not in ("institution_admin", "super_admin", "teacher"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student(student, user)
    if denied:
        return denied

    rows = (
        StudentPayment.query.filter_by(student_id=student.id)
        .order_by(StudentPayment.year.desc(), StudentPayment.month.desc(), StudentPayment.id.desc())
        .all()
    )
    return {
        "student_id": student.id,
        "studentId": student.id,
        "student_name": student.user.full_name if student.user else None,
        "studentName": student.user.full_name if student.user else None,
        "grade": student.grade,
        "payments": [row.to_dict() for row in rows],
        "count": len(rows),
    }, 200


def get_current_student_payment(student_id, user):
    if user.role not in ("institution_admin", "super_admin", "teacher"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student(student, user)
    if denied:
        return denied

    payload, payment = get_or_build_current_payment_payload(student.id)
    if payment:
        payload = _enrich_payment_dict(payment)
        payload["exists"] = True
    else:
        payload["exists"] = False
        payload["student_name"] = student.user.full_name if student.user else None
        payload["studentName"] = payload["student_name"]
        payload["grade"] = student.grade
        payload["registration_no"] = student.registration_no
        payload["registrationNo"] = student.registration_no

    return {
        "student_id": student.id,
        "studentId": student.id,
        "payment": payload,
        "payment_status": payload.get("payment_status"),
        "paymentStatus": payload.get("payment_status"),
    }, 200


def update_payment(payment_id, data, user):
    if user.role not in ("institution_admin", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    payment = StudentPayment.query.get(payment_id)
    if not payment:
        return {"errors": ["Payment not found"]}, 404

    denied = _authorize_student(payment.student, user)
    if denied:
        return denied

    if "amount" in data or "amount_due" in data or "amountDue" in data:
        amount = _parse_amount(
            data.get("amount") if data.get("amount") is not None else data.get("amount_due", data.get("amountDue"))
        )
        if amount is None:
            return {"errors": ["amount must be a number"]}, 400
        if amount < 0:
            return {"errors": ["amount must be zero or greater"]}, 400
        payment.amount = amount
        payment.amount_due = amount

    if "month" in data or "year" in data:
        month = _parse_month(data.get("month")) if "month" in data else payment.month
        year = _parse_year(data.get("year")) if "year" in data else payment.year
        if month is None or year is None:
            return {"errors": ["month and year must be valid"]}, 400
        new_period = billing_period_from_month_year(month, year)
        conflict = (
            StudentPayment.query.filter(
                StudentPayment.student_id == payment.student_id,
                StudentPayment.billing_period == new_period,
                StudentPayment.id != payment.id,
            ).first()
        )
        if conflict:
            return {"errors": ["Another payment already exists for that month"]}, 409
        payment.month = month
        payment.year = year
        payment.billing_period = new_period

    status_raw = data.get("payment_status") if "payment_status" in data else data.get("paymentStatus")
    if status_raw is not None:
        status = _parse_status(status_raw)
        if not status:
            return {"errors": ["payment_status must be Paid or Pending"]}, 400
        payment.payment_status = status

    if "payment_date" in data or "paymentDate" in data:
        payment.payment_date = _parse_payment_date(data.get("payment_date") or data.get("paymentDate"))

    if payment.payment_status == "Paid":
        if payment.payment_date is None:
            payment.payment_date = local_today()
        payment.paid_at = datetime.combine(payment.payment_date, datetime.min.time())
    else:
        payment.paid_at = None
        # Keep payment_date only if explicitly provided while pending; otherwise clear.
        if status_raw is not None:
            payment.payment_date = None

    payment.sync_period_fields()

    try:
        db.session.commit()
        db.session.refresh(payment)
        return {"success": True, "payment": _enrich_payment_dict(payment)}, 200
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to update payment"]}, 500
