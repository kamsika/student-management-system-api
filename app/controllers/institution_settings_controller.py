import re

from app.extensions import db
from app.models import Institution
from app.models.institution_model import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_NOTIFICATION_SETTINGS,
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
    DEFAULT_THEME_PRESET,
)
from app.utils import utc_now
from app.utils.color_utils import normalize_hex_color

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_LOGO_DATA_URL_LENGTH = 900_000


def _require_institution_admin(user):
    if not user or user.role != "institution_admin" or not user.institution_id:
        return None, ({"errors": ["Institution admin access required"]}, 403)
    institution = Institution.query.get(user.institution_id)
    if not institution:
        return None, ({"errors": ["Institution not found"]}, 404)
    return institution, None


def _validate_hex_color(value, label):
    if value is None or not str(value).strip():
        return [f"{label} is required"]
    return []


def _validate_logo_url(value):
    if value is None or value == "":
        return []
    text = str(value)
    if len(text) > MAX_LOGO_DATA_URL_LENGTH:
        return ["Logo file is too large. Use an image under 512 KB."]
    if text.startswith("data:image/"):
        allowed = ("image/png", "image/jpeg", "image/jpg", "image/svg+xml")
        header = text.split(",", 1)[0].lower()
        if not any(mime in header for mime in allowed):
            return ["Logo must be PNG, JPG, JPEG, or SVG."]
        return []
    if text.startswith("http://") or text.startswith("https://"):
        return []
    return ["Invalid logo format."]


def get_institution_settings(user):
    institution, error = _require_institution_admin(user)
    if error:
        return error
    return {
        "institution": institution.to_dict(),
        "admin": user.to_dict(),
    }, 200


def update_institution_profile(user, data):
    institution, error = _require_institution_admin(user)
    if error:
        return error

    name = (data.get("name") or data.get("institution_name") or "").strip()
    if not name:
        return {"errors": ["Institution name is required"]}, 400

    contact_email = (data.get("contact_email") or data.get("email") or "").strip()
    if contact_email and "@" not in contact_email:
        return {"errors": ["Enter a valid email address"]}, 400

    institution.name = name
    institution.contact_email = contact_email or None
    institution.phone = (data.get("phone") or data.get("phone_number") or "").strip() or None
    institution.address = (data.get("address") or "").strip() or None
    institution.description = (data.get("description") or "").strip() or None
    institution.updated_at = utc_now()

    db.session.commit()
    return {"message": "Profile updated successfully", "institution": institution.to_dict()}, 200


def update_institution_branding(user, data):
    institution, error = _require_institution_admin(user)
    if error:
        return error

    if data.get("reset_to_default"):
        institution.apply_default_branding()
        institution.updated_at = utc_now()
        db.session.commit()
        return {
            "message": "Branding reset to default",
            "institution": institution.to_dict(),
        }, 200

    errors = []
    if "primary_color" in data:
        errors.extend(_validate_hex_color(data.get("primary_color"), "Primary color"))
    if "secondary_color" in data:
        errors.extend(_validate_hex_color(data.get("secondary_color"), "Secondary color"))
    if "accent_color" in data:
        errors.extend(_validate_hex_color(data.get("accent_color"), "Accent color"))

    if "logo_url" in data or "logo" in data:
        logo = data.get("logo_url") if "logo_url" in data else data.get("logo")
        if logo is None:
            institution.logo_url = None
        else:
            logo_errors = _validate_logo_url(logo)
            if logo_errors:
                errors.extend(logo_errors)
            else:
                institution.logo_url = str(logo)

    if errors:
        return {"errors": errors}, 400

    if "primary_color" in data:
        institution.primary_color = normalize_hex_color(
            data.get("primary_color"),
            DEFAULT_PRIMARY_COLOR,
        )
    if "secondary_color" in data:
        institution.secondary_color = normalize_hex_color(
            data.get("secondary_color"),
            DEFAULT_SECONDARY_COLOR,
        )
    if "accent_color" in data:
        institution.accent_color = normalize_hex_color(
            data.get("accent_color"),
            DEFAULT_ACCENT_COLOR,
        )
    if "theme_preset" in data:
        institution.theme_preset = (data.get("theme_preset") or DEFAULT_THEME_PRESET).strip()

    institution.updated_at = utc_now()
    db.session.commit()
    return {"message": "Branding saved successfully", "institution": institution.to_dict()}, 200


def update_notification_settings(user, data):
    institution, error = _require_institution_admin(user)
    if error:
        return error

    current = institution.notification_settings_dict()
    keys = DEFAULT_NOTIFICATION_SETTINGS.keys()
    for key in keys:
        if key in data:
            current[key] = bool(data[key])

    institution.notification_settings = current
    institution.updated_at = utc_now()
    db.session.commit()
    return {
        "message": "Notification settings saved",
        "institution": institution.to_dict(),
    }, 200
