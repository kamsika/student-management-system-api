from app.extensions import db


def normalize_enrolled_subjects(raw_value):
    """Normalize enrolledSubjects from JSON / request body into a unique string list."""
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        # Support comma-separated strings from CSV / simple forms.
        parts = [part.strip() for part in text.replace(";", ",").split(",")]
        values = [part for part in parts if part]
    elif isinstance(raw_value, (list, tuple)):
        values = []
        for item in raw_value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                values.append(text)
    else:
        return []

    seen = set()
    unique = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


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
    # 128-element face-api.js descriptor used for recognition attendance.
    face_descriptor = db.Column(db.JSON, nullable=True)
    # Subjects the student is registered for, e.g. ["Chemistry", "Physics"].
    enrolled_subjects = db.Column(db.JSON, nullable=True)

    attendance_records = db.relationship("Attendance", backref="student", lazy=True)
    study_logs = db.relationship("StudyLog", backref="student", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("institution_id", "registration_no", name="uq_institution_registration"),
    )

    def get_enrolled_subjects(self):
        return normalize_enrolled_subjects(self.enrolled_subjects)

    def to_dict(self, include_face_descriptor=False):
        enrolled = self.get_enrolled_subjects()
        data = {
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
            "has_face_descriptor": bool(self.face_descriptor),
            "enrolled_subjects": enrolled,
            "enrolledSubjects": enrolled,
        }
        if include_face_descriptor:
            data["descriptor"] = self.face_descriptor
        return data
