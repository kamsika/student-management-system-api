from decimal import Decimal

from app.extensions import db


class BillingRecord(db.Model):
    __tablename__ = "billing_records"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    billing_period = db.Column(db.String(50), nullable=False)
    saas_flat_fee = db.Column(db.Numeric(10, 2), nullable=False)
    sms_count = db.Column(db.Integer, default=0, nullable=False)
    sms_unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total_amount_due = db.Column(db.Numeric(10, 2), nullable=False)
    payment_status = db.Column(
        db.Enum("Pending", "Paid", "Overdue", name="payment_status"),
        default="Pending",
        nullable=False,
    )

    def recalculate_total(self):
        sms_total = Decimal(str(self.sms_count)) * Decimal(str(self.sms_unit_price))
        self.total_amount_due = Decimal(str(self.saas_flat_fee)) + sms_total

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "billing_period": self.billing_period,
            "saas_flat_fee": float(self.saas_flat_fee),
            "sms_count": self.sms_count,
            "sms_unit_price": float(self.sms_unit_price),
            "total_amount_due": float(self.total_amount_due),
            "payment_status": self.payment_status,
        }
