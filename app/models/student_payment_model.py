from calendar import month_name
from datetime import date, datetime

from app.extensions import db
from app.utils import local_today, to_iso, utc_now


def billing_period_from_month_year(month: int, year: int) -> str:
    return f"{int(year):04d}-{int(month):02d}"


def month_year_from_billing_period(period: str):
    text = (period or "").strip()
    if len(text) == 7 and text[4] == "-":
        try:
            return int(text[5:7]), int(text[:4])
        except ValueError:
            return None, None
    return None, None


def month_label(month: int | None) -> str | None:
    if month is None:
        return None
    try:
        value = int(month)
    except (TypeError, ValueError):
        return None
    if 1 <= value <= 12:
        return month_name[value]
    return None


class StudentPayment(db.Model):
    """Monthly student fee payment record (Student → Payments one-to-many)."""

    __tablename__ = "student_payments"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    # Canonical period fields used by Fee Management APIs.
    month = db.Column(db.Integer, nullable=True, index=True)  # 1-12
    year = db.Column(db.Integer, nullable=True, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=True)
    payment_status = db.Column(
        db.Enum("Pending", "Paid", "Overdue", name="student_payment_status"),
        nullable=False,
        default="Pending",
        server_default="Pending",
    )
    payment_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    # Legacy / compatibility fields (kept in sync with month/year/amount/payment_date).
    billing_period = db.Column(db.String(7), nullable=False, index=True)  # YYYY-MM
    amount_due = db.Column(db.Numeric(10, 2), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("Student", backref="monthly_payments", lazy=True)

    __table_args__ = (
        db.UniqueConstraint(
            "student_id",
            "billing_period",
            name="uq_student_payment_period",
        ),
    )

    def sync_period_fields(self):
        """Keep month/year and billing_period aligned."""
        if self.month and self.year:
            self.billing_period = billing_period_from_month_year(self.month, self.year)
        elif self.billing_period:
            month, year = month_year_from_billing_period(self.billing_period)
            if month and year:
                self.month = month
                self.year = year

        if self.amount is not None and self.amount_due is None:
            self.amount_due = self.amount
        elif self.amount_due is not None and self.amount is None:
            self.amount = self.amount_due

        if self.payment_status == "Paid":
            if self.payment_date is None:
                self.payment_date = local_today()
            if self.paid_at is None:
                self.paid_at = datetime.combine(self.payment_date, datetime.min.time())
        else:
            # Pending / Overdue — clear paid markers unless an explicit payment_date is kept.
            self.paid_at = None

        now = utc_now()
        if self.created_at is None:
            self.created_at = now
        self.updated_at = now

    def to_dict(self):
        amount_value = None
        if self.amount is not None:
            amount_value = float(self.amount)
        elif self.amount_due is not None:
            amount_value = float(self.amount_due)

        month = self.month
        year = self.year
        if (month is None or year is None) and self.billing_period:
            month, year = month_year_from_billing_period(self.billing_period)

        payment_date = self.payment_date
        if payment_date is None and self.paid_at is not None:
            payment_date = self.paid_at.date() if isinstance(self.paid_at, datetime) else self.paid_at

        return {
            "id": self.id,
            "student_id": self.student_id,
            "studentId": self.student_id,
            "month": month,
            "year": year,
            "month_name": month_label(month),
            "monthName": month_label(month),
            "amount": amount_value,
            "amount_due": amount_value,
            "amountDue": amount_value,
            "payment_status": self.payment_status,
            "paymentStatus": self.payment_status,
            "payment_date": payment_date.isoformat() if isinstance(payment_date, date) else None,
            "paymentDate": payment_date.isoformat() if isinstance(payment_date, date) else None,
            "billing_period": self.billing_period,
            "billingPeriod": self.billing_period,
            "paid_at": to_iso(self.paid_at),
            "paidAt": to_iso(self.paid_at),
            "created_at": to_iso(self.created_at),
            "createdAt": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
            "updatedAt": to_iso(self.updated_at),
        }
