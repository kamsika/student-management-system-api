import secrets
import string

from app.models import User


def generate_admin_password(length: int = 12) -> str:
    """Generate a readable password with upper, lower, digit, and symbol."""
    if length < 8:
        length = 8

    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_symbol = any(c in "!@#$%&*" for c in password)
        if has_upper and has_lower and has_digit and has_symbol:
            return password


def generate_unique_admin_email(subdomain: str) -> str:
    safe_subdomain = "".join(c for c in subdomain.lower() if c.isalnum() or c == "-") or "center"
    base_email = f"admin.{safe_subdomain}@tuition.local"
    email = base_email
    counter = 1

    while User.query.filter_by(email=email).first():
        email = f"admin.{safe_subdomain}{counter}@tuition.local"
        counter += 1

    return email
