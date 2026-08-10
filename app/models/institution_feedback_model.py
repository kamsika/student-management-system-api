from app.extensions import db
from app.utils import to_iso, utc_now

RATING_FIELDS = ("overall_rating", "ui_rating", "ease_of_use_rating", "attendance_rating", "payment_rating", "performance_rating", "support_rating")

class InstitutionFeedback(db.Model):
    __tablename__ = "institution_feedback"
    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    overall_rating = db.Column(db.Integer, nullable=False)
    ui_rating = db.Column(db.Integer, nullable=False)
    ease_of_use_rating = db.Column(db.Integer, nullable=False)
    attendance_rating = db.Column(db.Integer, nullable=False)
    payment_rating = db.Column(db.Integer, nullable=False)
    performance_rating = db.Column(db.Integer, nullable=False)
    support_rating = db.Column(db.Integer, nullable=False)
    recommend_status = db.Column(db.Enum("Yes", "Maybe", "No", name="feedback_recommend_status"), nullable=False)
    improvement_comment = db.Column(db.Text)
    feature_request = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    institution = db.relationship("Institution", backref=db.backref("feedback_entries", lazy="dynamic"))
    __table_args__ = tuple(db.CheckConstraint(f"{field} BETWEEN 1 AND 5", name=f"ck_feedback_{field}") for field in RATING_FIELDS)

    def to_dict(self):
        result = {field: getattr(self, field) for field in RATING_FIELDS}
        result.update({"id": self.id, "institution_id": self.institution_id,
            "institution_name": self.institution.name if self.institution else None,
            "recommend_status": self.recommend_status, "improvement_comment": self.improvement_comment,
            "feature_request": self.feature_request, "created_at": to_iso(self.created_at), "updated_at": to_iso(self.updated_at)})
        return result
