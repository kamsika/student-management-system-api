from app.extensions import db
from app.utils import to_iso, utc_now


class Institution(db.Model):
    __tablename__ = "institutions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    subdomain = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.Enum("Active", "Suspended", name="institution_status"), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    users = db.relationship("User", backref="institution", lazy=True)
    classrooms = db.relationship("Classroom", backref="institution", lazy=True)
    students = db.relationship("Student", backref="institution", lazy=True)
    sms_logs = db.relationship("SmsLog", backref="institution", lazy=True)
    billing_records = db.relationship("BillingRecord", backref="institution", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "subdomain": self.subdomain,
            "status": self.status,
            "created_at": to_iso(self.created_at),
        }
