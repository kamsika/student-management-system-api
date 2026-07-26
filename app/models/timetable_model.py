from app.extensions import db


class Timetable(db.Model):
    """Schedule slot used by the Timetable Auto-Marking System."""

    __tablename__ = "timetables"

    id = db.Column(db.Integer, primary_key=True)
    # Multi-tenant school/center ID (also exposed as tenantId in the API).
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("institutions.id"),
        nullable=False,
        index=True,
    )
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True, index=True)
    day_of_week = db.Column(db.String(20), nullable=False, index=True)
    subject_name = db.Column(db.String(120), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)  # HH:MM
    end_time = db.Column(db.String(5), nullable=False)  # HH:MM

    institution = db.relationship("Institution", backref="timetable_slots", lazy=True)
    classroom = db.relationship("Classroom", backref="timetable_slots", lazy=True)
    student = db.relationship("Student", backref="timetable_slots", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "tenantId": self.tenant_id,
            "classroom_id": self.classroom_id,
            "classroomId": self.classroom_id,
            "student_id": self.student_id,
            "studentId": self.student_id,
            "day_of_week": self.day_of_week,
            "dayOfWeek": self.day_of_week,
            "subject_name": self.subject_name,
            "subjectName": self.subject_name,
            "start_time": self.start_time,
            "startTime": self.start_time,
            "end_time": self.end_time,
            "endTime": self.end_time,
            "classroom_name": self.classroom.name if self.classroom else None,
            "student_name": (
                self.student.user.full_name if self.student and self.student.user else None
            ),
            "registration_no": self.student.registration_no if self.student else None,
        }
