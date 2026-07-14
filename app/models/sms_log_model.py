from app.extensions import db
from app.utils import to_iso, utc_now


class SmsLog(db.Model):
    __tablename__ = "sms_logs"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    recipient_phone = db.Column(db.String(50), nullable=False)
    message_body = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.Enum("Sent", "Delivered", "Failed", name="sms_status"),
        nullable=False,
        default="Sent",
    )
    error_details = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "recipient_phone": self.recipient_phone,
            "message_body": self.message_body,
            "status": self.status,
            "error_details": self.error_details,
            "sent_at": to_iso(self.sent_at),
        }
