from app.extensions import db
from app.utils import to_iso


class StudentPayment(db.Model):
    """Monthly fee status for one student."""

    __tablename__ = "student_payments"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    billing_period = db.Column(db.String(7), nullable=False, index=True)  # YYYY-MM
    amount_due = db.Column(db.Numeric(10, 2), nullable=True)
    payment_status = db.Column(
        db.Enum("Pending", "Paid", "Overdue", name="student_payment_status"),
        nullable=False,
        default="Pending",
        server_default="Pending",
    )
    paid_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("Student", backref="monthly_payments", lazy=True)

    __table_args__ = (
        db.UniqueConstraint(
            "student_id",
            "billing_period",
            name="uq_student_payment_period",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "billing_period": self.billing_period,
            "amount_due": float(self.amount_due) if self.amount_due is not None else None,
            "payment_status": self.payment_status,
            "paid_at": to_iso(self.paid_at),
        }
