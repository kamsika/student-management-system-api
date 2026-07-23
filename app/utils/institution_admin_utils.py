import secrets
import string

from app.models import User


def generate_admin_password(length: int = 12) -> str:
    """Generate a copy-safe password with upper, lower, and digit characters.

    Avoids ambiguous characters (0/O, 1/l/I) and symbols that are easy to
    mistype when sharing credentials.
    """
    if length < 8:
        length = 8

    upper = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lower = "abcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    alphabet = upper + lower + digits

    while True:
        password_chars = [
            secrets.choice(upper),
            secrets.choice(lower),
            secrets.choice(digits),
        ]
        password_chars.extend(secrets.choice(alphabet) for _ in range(length - 3))
        secrets.SystemRandom().shuffle(password_chars)
        password = "".join(password_chars)
        if (
            any(c in upper for c in password)
            and any(c in lower for c in password)
            and any(c in digits for c in password)
        ):
            return password


def generate_unique_admin_email(subdomain: str) -> str:
    # Use a normal TLD so browser/email validators accept the login form.
    safe_subdomain = "".join(c for c in subdomain.lower() if c.isalnum() or c == "-") or "center"
    base_email = f"admin.{safe_subdomain}@studentmgt.app"
    email = base_email
    counter = 1

    while User.query.filter_by(email=email).first():
        email = f"admin.{safe_subdomain}{counter}@studentmgt.app"
        counter += 1

    return email
