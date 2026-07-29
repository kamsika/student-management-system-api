from app.extensions import db
from app.utils import to_iso, utc_now
from app.utils.color_utils import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
    normalize_hex_color,
)

DEFAULT_THEME_PRESET = "royal_blue"

DEFAULT_NOTIFICATION_SETTINGS = {
    "email_notifications": True,
    "attendance_alerts": True,
    "fee_reminder_alerts": True,
    "exam_notifications": True,
    "announcement_notifications": True,
}


class Institution(db.Model):
    __tablename__ = "institutions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    subdomain = db.Column(db.String(100), unique=True, nullable=False, index=True)
    status = db.Column(db.Enum("Active", "Suspended", name="institution_status"), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=True)

    contact_email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    address = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)

    logo_url = db.Column(db.Text, nullable=True)
    primary_color = db.Column(db.String(7), default=DEFAULT_PRIMARY_COLOR, nullable=False)
    secondary_color = db.Column(db.String(7), default=DEFAULT_SECONDARY_COLOR, nullable=False)
    accent_color = db.Column(db.String(7), default=DEFAULT_ACCENT_COLOR, nullable=False)
    theme_preset = db.Column(db.String(50), default=DEFAULT_THEME_PRESET, nullable=False)
    notification_settings = db.Column(db.JSON, nullable=True)

    users = db.relationship("User", backref="institution", lazy=True)
    classrooms = db.relationship("Classroom", backref="institution", lazy=True)
    students = db.relationship("Student", backref="institution", lazy=True)
    sms_logs = db.relationship("SmsLog", backref="institution", lazy=True)
    billing_records = db.relationship("BillingRecord", backref="institution", lazy=True)

    def notification_settings_dict(self):
        base = dict(DEFAULT_NOTIFICATION_SETTINGS)
        if isinstance(self.notification_settings, dict):
            base.update(self.notification_settings)
        return base

    def to_dict(self, include_branding=True):
        data = {
            "id": self.id,
            "name": self.name,
            "institution_name": self.name,
            "subdomain": self.subdomain,
            "status": self.status,
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at) if self.updated_at else None,
            "contact_email": self.contact_email,
            "email": self.contact_email,
            "phone": self.phone,
            "phone_number": self.phone,
            "address": self.address,
            "description": self.description,
        }
        if include_branding:
            data.update(
                {
                    "logo": self.logo_url,
                    "logo_url": self.logo_url,
                    "primary_color": normalize_hex_color(
                        self.primary_color,
                        DEFAULT_PRIMARY_COLOR,
                    ),
                    "secondary_color": normalize_hex_color(
                        self.secondary_color,
                        DEFAULT_SECONDARY_COLOR,
                    ),
                    "accent_color": normalize_hex_color(
                        self.accent_color,
                        DEFAULT_ACCENT_COLOR,
                    ),
                    "theme_preset": self.theme_preset or DEFAULT_THEME_PRESET,
                    "notifications": self.notification_settings_dict(),
                    "notification_settings": self.notification_settings_dict(),
                }
            )
        return data

    def apply_default_branding(self):
        self.logo_url = None
        self.primary_color = DEFAULT_PRIMARY_COLOR
        self.secondary_color = DEFAULT_SECONDARY_COLOR
        self.accent_color = DEFAULT_ACCENT_COLOR
        self.theme_preset = DEFAULT_THEME_PRESET
