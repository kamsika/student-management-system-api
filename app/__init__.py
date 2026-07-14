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
    sms_log_bp,
    study_log_bp,
    student_bp,
)
from app.utils.alert_engine import run_absentee_sweeper

scheduler = BackgroundScheduler()


def _ensure_database_exists(app):
    import os
    from urllib.parse import quote_plus

    import pymysql

    db_name = os.getenv("DB_NAME")
    if not db_name:
        return

    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "3306"))

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
    CORS(app, origins=app.config["CORS_ORIGINS"], supports_credentials=True)

    app.register_blueprint(auth_bp)
    app.register_blueprint(institution_bp)
    app.register_blueprint(classroom_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(study_log_bp)
    app.register_blueprint(sms_log_bp)
    app.register_blueprint(student_bp)

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
        _seed_super_admin(app)

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
