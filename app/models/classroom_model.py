from app.extensions import db


class Classroom(db.Model):
    __tablename__ = "classrooms"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    grade = db.Column(db.String(50), nullable=True)
    schedule_start_time = db.Column(db.Time, nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # [{"subject": "Maths", "teacher_id": 1}, ...]
    subject_teachers = db.Column(db.JSON, nullable=True)

    attendance_records = db.relationship("Attendance", backref="classroom", lazy=True)

    def get_subject_teachers(self):
        raw = self.subject_teachers
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject") or item.get("subjectName") or "").strip()
            teacher_id = item.get("teacher_id", item.get("teacherId"))
            try:
                teacher_id = int(teacher_id)
            except (TypeError, ValueError):
                continue
            if subject and teacher_id:
                result.append({"subject": subject, "teacher_id": teacher_id})
        return result

    def to_dict(self):
        assignments = self.get_subject_teachers()
        teacher_names = {}
        if assignments:
            from app.models import User

            ids = {item["teacher_id"] for item in assignments}
            for teacher in User.query.filter(User.id.in_(ids)).all():
                teacher_names[teacher.id] = teacher.full_name

        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "name": self.name,
            "grade": self.grade,
            "schedule_start_time": self.schedule_start_time.isoformat() if self.schedule_start_time else None,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else None,
            "subject_teachers": [
                {
                    "subject": item["subject"],
                    "subjectName": item["subject"],
                    "teacher_id": item["teacher_id"],
                    "teacherId": item["teacher_id"],
                    "teacher_name": teacher_names.get(item["teacher_id"]),
                    "teacherName": teacher_names.get(item["teacher_id"]),
                }
                for item in assignments
            ],
        }
