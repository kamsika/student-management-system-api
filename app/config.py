import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


def build_database_url():
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    user = os.getenv("DB_USER", "root")
    password = quote_plus(os.getenv("DB_PASSWORD", ""))
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    name = os.getenv("DB_NAME", "student_mgt_sys")

    if password:
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}"
    return f"mysql+pymysql://{user}@{host}:{port}/{name}"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-key")
    SQLALCHEMY_DATABASE_URI = build_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "1440")) * 60

    # Always allow local frontend + known Vercel deployments.
    # Preview URLs change per deploy (client-*.vercel.app), so we also allow
    # https://*.vercel.app via regex unless CORS_ALLOW_VERCEL=false.
    _default_cors_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://student-tracking-sys.vercel.app",
        "https://client-aj4y25kce-kamsikas-projects.vercel.app",
    ]
    _cors_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", ",".join(_default_cors_origins)).split(",")
        if origin.strip()
    ]
    for origin in _default_cors_origins:
        if origin not in _cors_origins:
            _cors_origins.append(origin)

    _frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    if _frontend_url and _frontend_url not in _cors_origins:
        _cors_origins.append(_frontend_url)

    _allow_vercel = os.getenv("CORS_ALLOW_VERCEL", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    _vercel_regex = r"https://.*\.vercel\.app"
    if _allow_vercel and _vercel_regex not in _cors_origins:
        _cors_origins.append(_vercel_regex)

    CORS_ORIGINS = _cors_origins
    CORS_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    CORS_ALLOW_HEADERS = ["Content-Type", "Authorization", "X-Requested-With"]
    CORS_EXPOSE_HEADERS = ["Content-Type"]
    CORS_MAX_AGE = int(os.getenv("CORS_MAX_AGE", "86400"))

    SAAS_FLAT_FEE = float(os.getenv("SAAS_FLAT_FEE", "5000.00"))
    SMS_UNIT_PRICE = float(os.getenv("SMS_UNIT_PRICE", "2.50"))
    SMS_GATEWAY_URL = os.getenv("SMS_GATEWAY_URL", "")
    SMS_GATEWAY_API_KEY = os.getenv("SMS_GATEWAY_API_KEY", "")
