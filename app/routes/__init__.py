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
from app.routes.subject_routes import subject_bp
from app.routes.face_routes import face_bp
from app.routes.payment_routes import payment_bp
from app.routes.admin_routes import admin_bp
from app.routes.tenant_routes import tenant_bp
from app.routes.tuition_routes import tuition_bp
from app.routes.super_admin_routes import super_admin_bp
from app.routes.feedback_routes import feedback_bp

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
    "subject_bp",
    "face_bp",
    "payment_bp",
    "tenant_bp",
    "tuition_bp",
    "admin_bp",
    "super_admin_bp",
    "feedback_bp",
]
