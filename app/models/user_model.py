from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils import to_iso


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.Enum(
            "super_admin",
            "institution_admin",
            "teacher",
            "student",
            "parent",
            name="user_role",
        ),
        nullable=False,
        index=True,
    )
    full_name = db.Column(db.String(255), nullable=False)
    phone_number = db.Column(db.String(50), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    taught_classrooms = db.relationship("Classroom", backref="teacher", lazy=True, foreign_keys="Classroom.teacher_id")
    student_profile = db.relationship("Student", backref="user", lazy=True, foreign_keys="Student.user_id", uselist=False)
    parent_students = db.relationship("Student", backref="parent", lazy=True, foreign_keys="Student.parent_id")

    def set_password(self, raw_password):
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password, raw_password)

    def to_dict(self, include_institution=False):
        data = {
            "id": self.id,
            "institution_id": self.institution_id,
            "email": self.email,
            "role": self.role,
            "full_name": self.full_name,
            "phone_number": self.phone_number,
            "is_active": self.is_active,
        }
        if include_institution and self.institution:
            data["institution"] = self.institution.to_dict()
        return data
