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
    face_embedding = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    student = db.relationship("Student", backref=db.backref("face_data", uselist=False))

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "face_embedding": self.face_embedding,
            "has_face": bool(self.face_embedding),
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
        }
