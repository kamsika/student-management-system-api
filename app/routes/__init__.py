from app.routes.auth_routes import auth_bp
from app.routes.institution_routes import institution_bp
from app.routes.classroom_routes import classroom_bp
from app.routes.attendance_routes import attendance_bp
from app.routes.study_log_routes import study_log_bp
from app.routes.sms_log_routes import sms_log_bp
from app.routes.student_routes import student_bp
from app.routes.parent_routes import parent_bp
from app.routes.teacher_routes import teacher_bp
from app.routes.timetable_routes import timetable_bp

__all__ = [
    "auth_bp",
    "institution_bp",
    "classroom_bp",
    "attendance_bp",
    "study_log_bp",
    "sms_log_bp",
    "student_bp",
    "parent_bp",
    "teacher_bp",
    "timetable_bp",
]
