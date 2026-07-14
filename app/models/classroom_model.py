from app.extensions import db
from app.utils import to_iso


class Classroom(db.Model):
    __tablename__ = "classrooms"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    schedule_start_time = db.Column(db.Time, nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    attendance_records = db.relationship("Attendance", backref="classroom", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "name": self.name,
            "schedule_start_time": self.schedule_start_time.isoformat() if self.schedule_start_time else None,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else None,
        }
