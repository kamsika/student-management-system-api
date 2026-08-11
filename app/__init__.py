from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from app.config import Config
from app.extensions import db, jwt
from app.routes import (
    admin_bp,
    attendance_bp,
    auth_bp,
    classroom_bp,
    face_bp,
    feedback_bp,
    institution_bp,
    parent_bp,
    payment_bp,
    sms_log_bp,
    study_log_bp,
    student_bp,
    subject_bp,
    super_admin_bp,
    teacher_bp,
    tenant_bp,
    timetable_bp,
    tuition_bp,
)
from app.utils.alert_engine import run_absentee_sweeper

scheduler = BackgroundScheduler()


def _ensure_database_exists(app):
    import pymysql
    from sqlalchemy.engine import make_url

    database_url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
    db_name = database_url.database
    if not db_name:
        return

    connection = pymysql.connect(
        host=database_url.host or "localhost",
        user=database_url.username or "root",
        password=database_url.password or "",
        port=database_url.port or 3306,
        charset="utf8mb4",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        connection.commit()
    finally:
        connection.close()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    jwt.init_app(app)
    # Explicit origins/methods/headers so browser preflight (OPTIONS) succeeds
    # from Vercel + localhost. Regex in CORS_ORIGINS covers *.vercel.app previews.
    CORS(
        app,
        origins=app.config["CORS_ORIGINS"],
        methods=app.config["CORS_METHODS"],
        allow_headers=app.config["CORS_ALLOW_HEADERS"],
        expose_headers=app.config["CORS_EXPOSE_HEADERS"],
        supports_credentials=True,
        max_age=app.config["CORS_MAX_AGE"],
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(face_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(institution_bp)
    app.register_blueprint(classroom_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(study_log_bp)
    app.register_blueprint(sms_log_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(parent_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(timetable_bp)
    app.register_blueprint(subject_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(tenant_bp)
    app.register_blueprint(super_admin_bp)
    app.register_blueprint(tuition_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"errors": ["Resource not found"]}), 404

    @app.errorhandler(500)
    def server_error(_error):
        return jsonify({"errors": ["Internal server error"]}), 500

    @app.get("/api/health")
    def health():
        return {"status": "ok"}, 200

    with app.app_context():
        _ensure_database_exists(app)
        db.create_all()
        _migrate_legacy_face_descriptors()
        _apply_schema_updates(app)
        _seed_super_admin(app)
        _seed_demo_data(app)

    if not scheduler.running:
        scheduler.add_job(
            func=_scheduled_sweeper,
            trigger="interval",
            minutes=1,
            id="absentee_sweeper",
            replace_existing=True,
            args=[app],
        )
        scheduler.add_job(
            func=_scheduled_tuition_invoices,
            trigger="cron",
            hour=0,
            minute=10,
            id="monthly_tuition_invoices",
            replace_existing=True,
            args=[app],
        )
        scheduler.start()

    return app


def _scheduled_sweeper(app):
    with app.app_context():
        try:
            run_absentee_sweeper()
        except Exception:
            db.session.rollback()


def _scheduled_tuition_invoices(app):
    from app.controllers.tuition_controller import run_scheduled_invoice_generation

    with app.app_context():
        run_scheduled_invoice_generation()


def _migrate_legacy_face_descriptors():
    """Copy students.face_descriptor into face_data when missing (one row per student)."""
    from app.models import FaceData, Student
    from app.utils import utc_now

    try:
        rows = Student.query.filter(Student.face_descriptor.isnot(None)).all()
        for student in rows:
            if not student.face_descriptor:
                continue
            existing = FaceData.query.filter_by(student_id=student.id).first()
            if existing:
                continue
            now = utc_now()
            db.session.add(
                FaceData(
                    student_id=student.id,
                    institution_id=student.institution_id,
                    face_embedding=student.face_descriptor,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.session.commit()
    except Exception:
        db.session.rollback()


def _apply_schema_updates(app):
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()

    if "users" in table_names:
        user_columns = {column["name"]: column for column in inspector.get_columns("users")}
        password_col = user_columns.get("password")
        # Ensure password hashes are never truncated (breaks login verification).
        if password_col is not None:
            db.session.execute(text("ALTER TABLE users MODIFY COLUMN password VARCHAR(512) NOT NULL"))
        if "last_login_at" not in user_columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL"))

    if "students" in table_names:
        existing = {column["name"] for column in inspector.get_columns("students")}
        additions = {
            "grade": "VARCHAR(50) NULL",
            "section": "VARCHAR(50) NULL",
            "gender": "VARCHAR(20) NULL",
            "face_descriptor": "JSON NULL",
            "enrolled_subjects": "JSON NULL",
        }

        for column_name, column_type in additions.items():
            if column_name not in existing:
                db.session.execute(text(f"ALTER TABLE students ADD COLUMN {column_name} {column_type}"))

    if "classrooms" in table_names:
        classroom_cols = {column["name"] for column in inspector.get_columns("classrooms")}
        if "grade" not in classroom_cols:
            db.session.execute(text("ALTER TABLE classrooms ADD COLUMN grade VARCHAR(50) NULL"))
        if "subject_teachers" not in classroom_cols:
            db.session.execute(text("ALTER TABLE classrooms ADD COLUMN subject_teachers JSON NULL"))

    if "subjects" in table_names:
        subject_cols = {column["name"] for column in inspector.get_columns("subjects")}
        if "description" not in subject_cols:
            db.session.execute(text("ALTER TABLE subjects ADD COLUMN description TEXT NULL"))
        if "is_active" not in subject_cols:
            db.session.execute(text("ALTER TABLE subjects ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))

    # Timetable auto-marking: ensure tenant_id exists on older databases.
    if "timetables" in table_names:
        timetable_cols = {column["name"] for column in inspector.get_columns("timetables")}
        if "tenant_id" not in timetable_cols:
            db.session.execute(
                text(
                    "ALTER TABLE timetables ADD COLUMN tenant_id INT NULL, "
                    "ADD INDEX ix_timetables_tenant_id (tenant_id)"
                )
            )
            # Backfill from classroom or student institution when possible.
            db.session.execute(
                text(
                    """
                    UPDATE timetables t
                    LEFT JOIN classrooms c ON c.id = t.classroom_id
                    LEFT JOIN students s ON s.id = t.student_id
                    SET t.tenant_id = COALESCE(c.institution_id, s.institution_id)
                    WHERE t.tenant_id IS NULL
                    """
                )
            )
            db.session.execute(
                text(
                    "ALTER TABLE timetables MODIFY COLUMN tenant_id INT NOT NULL, "
                    "ADD CONSTRAINT fk_timetables_tenant "
                    "FOREIGN KEY (tenant_id) REFERENCES institutions(id)"
                )
            )
            timetable_cols.add("tenant_id")

        if "teacher_id" not in timetable_cols:
            db.session.execute(
                text(
                    "ALTER TABLE timetables ADD COLUMN teacher_id INT NULL, "
                    "ADD INDEX ix_timetables_teacher_id (teacher_id)"
                )
            )
            try:
                db.session.execute(
                    text(
                        "ALTER TABLE timetables "
                        "ADD CONSTRAINT fk_timetables_teacher "
                        "FOREIGN KEY (teacher_id) REFERENCES users(id)"
                    )
                )
            except Exception:
                # Constraint may already exist or engine may not support inline add.
                pass

    # Attendance subject support for timetable auto-marking.
    if "attendance" in table_names:
        attendance_cols = {column["name"] for column in inspector.get_columns("attendance")}
        if "subject_name" not in attendance_cols:
            db.session.execute(
                text(
                    "ALTER TABLE attendance "
                    "ADD COLUMN subject_name VARCHAR(120) NOT NULL DEFAULT ''"
                )
            )
            attendance_cols.add("subject_name")

        if "marked_via" not in attendance_cols:
            db.session.execute(
                text(
                    "ALTER TABLE attendance "
                    "ADD COLUMN marked_via VARCHAR(20) NOT NULL DEFAULT ''"
                )
            )
            attendance_cols.add("marked_via")

        if "subject_id" not in attendance_cols:
            db.session.execute(
                text(
                    "ALTER TABLE attendance "
                    "ADD COLUMN subject_id INT NULL"
                )
            )
            attendance_cols.add("subject_id")
            try:
                db.session.execute(
                    text(
                        "ALTER TABLE attendance "
                        "ADD CONSTRAINT fk_attendance_subject "
                        "FOREIGN KEY (subject_id) REFERENCES subjects(id)"
                    )
                )
            except Exception:
                pass
            try:
                db.session.execute(
                    text("CREATE INDEX ix_attendance_subject_id ON attendance (subject_id)")
                )
            except Exception:
                pass

        # Refresh inspector indexes after possible column add.
        inspector = inspect(db.engine)
        index_names = {index["name"] for index in inspector.get_indexes("attendance")}
        # Also check unique constraints reported as indexes on MySQL.
        if "uq_student_classroom_date" in index_names:
            db.session.execute(text("ALTER TABLE attendance DROP INDEX uq_student_classroom_date"))
            index_names.discard("uq_student_classroom_date")
        if "uq_student_classroom_date_subject" not in index_names:
            db.session.execute(
                text(
                    "ALTER TABLE attendance "
                    "ADD UNIQUE KEY uq_student_classroom_date_subject "
                    "(student_id, classroom_id, date, subject_name)"
                )
            )

    # Student fee payments: add month/year/amount/payment_date timestamps.
    if "student_payments" in table_names:
        payment_cols = {column["name"] for column in inspector.get_columns("student_payments")}
        payment_additions = {
            "month": "INT NULL",
            "year": "INT NULL",
            "amount": "DECIMAL(10,2) NULL",
            "payment_date": "DATE NULL",
            "collected_by": "INT NULL",
            "created_at": "DATETIME NULL",
            "updated_at": "DATETIME NULL",
        }
        for column_name, column_type in payment_additions.items():
            if column_name not in payment_cols:
                db.session.execute(
                    text(f"ALTER TABLE student_payments ADD COLUMN {column_name} {column_type}")
                )
                payment_cols.add(column_name)

        # Backfill month/year from billing_period (YYYY-MM).
        db.session.execute(
            text(
                """
                UPDATE student_payments
                SET
                  year = CASE
                    WHEN year IS NULL AND billing_period IS NOT NULL AND CHAR_LENGTH(billing_period) = 7
                      THEN CAST(SUBSTRING(billing_period, 1, 4) AS UNSIGNED)
                    ELSE year
                  END,
                  month = CASE
                    WHEN month IS NULL AND billing_period IS NOT NULL AND CHAR_LENGTH(billing_period) = 7
                      THEN CAST(SUBSTRING(billing_period, 6, 2) AS UNSIGNED)
                    ELSE month
                  END,
                  amount = COALESCE(amount, amount_due),
                  payment_date = COALESCE(payment_date, DATE(paid_at)),
                  created_at = COALESCE(created_at, UTC_TIMESTAMP()),
                  updated_at = COALESCE(updated_at, UTC_TIMESTAMP())
                """
            )
        )

    if "institutions" in table_names:
        institution_cols = {column["name"] for column in inspector.get_columns("institutions")}
        institution_additions = {
            "updated_at": "DATETIME NULL",
            "contact_email": "VARCHAR(255) NULL",
            "phone": "VARCHAR(50) NULL",
            "address": "TEXT NULL",
            "description": "TEXT NULL",
            "logo_url": "LONGTEXT NULL",
            "primary_color": "VARCHAR(7) NOT NULL DEFAULT '#0047AB'",
            "secondary_color": "VARCHAR(7) NOT NULL DEFAULT '#FFFFFF'",
            "accent_color": "VARCHAR(7) NOT NULL DEFAULT '#F9BF15'",
            "theme_preset": "VARCHAR(50) NOT NULL DEFAULT 'royal_blue'",
            "notification_settings": "JSON NULL",
        }
        for column_name, column_type in institution_additions.items():
            if column_name not in institution_cols:
                db.session.execute(
                    text(f"ALTER TABLE institutions ADD COLUMN {column_name} {column_type}")
                )

    if "face_data" in table_names:
        face_cols = {column["name"] for column in inspector.get_columns("face_data")}
        if "institution_id" not in face_cols:
            db.session.execute(
                text(
                    "ALTER TABLE face_data ADD COLUMN institution_id INT NULL, "
                    "ADD INDEX ix_face_data_institution_id (institution_id)"
                )
            )
        if "registered_by" not in face_cols:
            db.session.execute(
                text(
                    "ALTER TABLE face_data ADD COLUMN registered_by INT NULL, "
                    "ADD INDEX ix_face_data_registered_by (registered_by)"
                )
            )
        # Backfill institution_id from students when missing.
        db.session.execute(
            text(
                """
                UPDATE face_data fd
                INNER JOIN students s ON s.id = fd.student_id
                SET fd.institution_id = s.institution_id
                WHERE fd.institution_id IS NULL
                """
            )
        )

    db.session.commit()


def _seed_super_admin(app):
    from app.models import User

    if not User.query.filter_by(role="super_admin").first():
        admin = User(
            institution_id=None,
            email="superadmin@platform.com",
            role="super_admin",
            full_name="Super Admin",
            phone_number="+94000000000",
            is_active=True,
        )
        admin.set_password("SuperAdmin@123")
        db.session.add(admin)
        db.session.commit()


def _seed_demo_data(app):
    from app.seeders.demo_seeder import seed_demo_data

    try:
        seed_demo_data(force=False)
    except Exception:
        db.session.rollback()
