from app.extensions import db
from app.utils import to_iso


class Subject(db.Model):
    __tablename__ = "subjects"
    __table_args__ = (
        db.UniqueConstraint("institution_id", "name", name="uq_subjects_institution_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(40), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)

    institution = db.relationship("Institution", backref="subjects", lazy=True)
    teacher = db.relationship("User", backref="assigned_subjects", lazy=True, foreign_keys=[teacher_id])

    def to_dict(self):
        data = {
            "id": self.id,
            "institution_id": self.institution_id,
            "institutionId": self.institution_id,
            "name": self.name,
            "code": self.code,
            "teacher_id": self.teacher_id,
            "teacherId": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else None,
            "teacherName": self.teacher.full_name if self.teacher else None,
            "description": self.description,
            "is_active": self.is_active,
            "isActive": self.is_active,
            "created_at": to_iso(self.created_at) if self.created_at else None,
            "createdAt": to_iso(self.created_at) if self.created_at else None,
        }
        from app.controllers.tuition_controller import current_subject_fee

        current_fee = current_subject_fee(self.id, self.institution_id)
        data["current_fee"] = current_fee.to_dict() if current_fee else None
        data["currentFee"] = data["current_fee"]
        return data
