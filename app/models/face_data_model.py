from app.extensions import db
from app.utils import to_iso, utc_now


class FaceData(db.Model):
    """One face profile per student — stores a 128-d embedding only (no raw images)."""

    __tablename__ = "face_data"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("students.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    institution_id = db.Column(
        db.Integer,
        db.ForeignKey("institutions.id"),
        nullable=True,
        index=True,
    )
    face_embedding = db.Column(db.JSON, nullable=False)
    registered_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    student = db.relationship("Student", backref=db.backref("face_data", uselist=False))
    registered_by_user = db.relationship("User", foreign_keys=[registered_by])

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "institution_id": self.institution_id,
            "face_embedding": self.face_embedding,
            "has_face": bool(self.face_embedding),
            "registered_by": self.registered_by,
            "registration_date": to_iso(self.created_at),
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
        }
