from app.extensions import db


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    registration_no = db.Column(db.String(100), nullable=False, index=True)
    grade = db.Column(db.String(50), nullable=True)
    section = db.Column(db.String(50), nullable=True)
    gender = db.Column(db.String(20), nullable=True)

    attendance_records = db.relationship("Attendance", backref="student", lazy=True)
    study_logs = db.relationship("StudyLog", backref="student", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("institution_id", "registration_no", name="uq_institution_registration"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "user_id": self.user_id,
            "parent_id": self.parent_id,
            "registration_no": self.registration_no,
            "full_name": self.user.full_name if self.user else None,
            "email": self.user.email if self.user else None,
            "contact": self.user.phone_number if self.user else None,
            "grade": self.grade,
            "section": self.section,
            "gender": self.gender,
            "parent_name": self.parent.full_name if self.parent else None,
            "parent_phone": self.parent.phone_number if self.parent else None,
        }
