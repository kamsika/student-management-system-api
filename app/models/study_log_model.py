from app.extensions import db
from app.utils import to_iso


class StudyLog(db.Model):
    __tablename__ = "study_logs"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "start_time": to_iso(self.start_time),
            "end_time": to_iso(self.end_time),
            "duration_minutes": self.duration_minutes,
        }
