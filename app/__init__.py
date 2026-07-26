from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from app.config import Config
from app.extensions import db, jwt
from app.routes import (
    attendance_bp,
    auth_bp,
    classroom_bp,
    institution_bp,
    parent_bp,
    sms_log_bp,
    study_log_bp,
    student_bp,
    teacher_bp,
    timetable_bp,
)
from app.utils.alert_engine import run_absentee_sweeper

scheduler = BackgroundScheduler()


def _ensure_database_exists(app):
    import os
    from urllib.parse import quote_plus

    import pymysql

    db_name = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE")
    if not db_name:
        return

    user = os.getenv("DB_USER") or os.getenv("MYSQLUSER", "root")
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD", "")
    host = os.getenv("DB_HOST") or os.getenv("MYSQLHOST", "localhost")
    port = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT", "3306"))

    connection = pymysql.connect(
        host=host,
        user=user,
        password=password,
        port=port,
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
    app.register_blueprint(institution_bp)
    app.register_blueprint(classroom_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(study_log_bp)
    app.register_blueprint(sms_log_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(parent_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(timetable_bp)

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
        scheduler.start()

    return app


def _scheduled_sweeper(app):
    with app.app_context():
        try:
            run_absentee_sweeper()
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
