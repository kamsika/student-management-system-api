from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils import to_iso


# pbkdf2 hashes stay well under VARCHAR limits and are widely compatible.
_PASSWORD_HASH_METHOD = "pbkdf2:sha256"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password = db.Column(db.String(512), nullable=False)
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
        if raw_password is None:
            raise ValueError("Password cannot be empty")
        password_text = str(raw_password)
        if not password_text:
            raise ValueError("Password cannot be empty")
        self.password = generate_password_hash(password_text, method=_PASSWORD_HASH_METHOD)

    def check_password(self, raw_password):
        if not self.password or raw_password is None:
            return False
        try:
            return check_password_hash(self.password, str(raw_password))
        except (ValueError, TypeError) as exc:
            print(f"[AUTH] check_password_hash error for user_id={self.id}: {exc}")
            return False

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
