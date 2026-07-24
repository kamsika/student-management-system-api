from app.extensions import db
from app.utils import to_iso


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    arrival_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(
        db.Enum("Present", "Absent", "Late", name="attendance_status"),
        nullable=False,
    )
    marked_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    marker = db.relationship("User", foreign_keys=[marked_by])

    __table_args__ = (
        db.UniqueConstraint("student_id", "classroom_id", "date", name="uq_student_classroom_date"),
    )

    def to_dict(self):
        classroom = self.classroom
        student = self.student
        return {
            "id": self.id,
            "student_id": self.student_id,
            "classroom_id": self.classroom_id,
            "class_id": self.classroom_id,
            "center_id": classroom.institution_id if classroom else None,
            "institution_id": classroom.institution_id if classroom else None,
            "classroom_name": classroom.name if classroom else None,
            "date": to_iso(self.date),
            "arrival_time": to_iso(self.arrival_time),
            "status": self.status,
            "marked_by": self.marked_by,
            "student_name": student.user.full_name if student and student.user else None,
            "registration_no": student.registration_no if student else None,
        }
