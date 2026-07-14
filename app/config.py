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
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    SAAS_FLAT_FEE = float(os.getenv("SAAS_FLAT_FEE", "5000.00"))
    SMS_UNIT_PRICE = float(os.getenv("SMS_UNIT_PRICE", "2.50"))
    SMS_GATEWAY_URL = os.getenv("SMS_GATEWAY_URL", "")
    SMS_GATEWAY_API_KEY = os.getenv("SMS_GATEWAY_API_KEY", "")
