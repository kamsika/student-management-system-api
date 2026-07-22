from datetime import datetime

from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import BillingRecord, Institution, User
from app.utils import utc_now


def login_user(data):
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return {"errors": ["Email and password are required"]}, 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return {"errors": ["Invalid email or password"]}, 401

    if not user.is_active:
        return {"errors": ["Account is deactivated"]}, 403

    if user.role != "super_admin" and user.institution:
        if user.institution.status == "Suspended":
            return {"errors": ["Institution is suspended"]}, 403

    token = create_access_token(
        identity=str(user.id),
        additional_claims={
            "role": user.role,
            "institution_id": user.institution_id,
        },
    )

    return {
        "access_token": token,
        "user": user.to_dict(include_institution=True),
    }, 200


def get_authenticated_user(user):
    if not user:
        return {"errors": ["Unauthorized"]}, 401

    if not user.is_active:
        return {"errors": ["Account is deactivated"]}, 403

    if user.role != "super_admin" and user.institution:
        if user.institution.status == "Suspended":
            return {"errors": ["Institution is suspended"]}, 403

    return {"user": user.to_dict(include_institution=True)}, 200


def register_institution(data):
    name = (data.get("name") or "").strip()
    subdomain = (data.get("subdomain") or "").strip().lower()
    admin_name = (data.get("admin_name") or "").strip()
    admin_email = (data.get("admin_email") or "").strip().lower()
    admin_password = data.get("admin_password") or ""
    admin_phone = (data.get("admin_phone") or "").strip()

    errors = []
    if not name:
        errors.append("Institution name is required")
    if not subdomain:
        errors.append("Subdomain is required")
    if not admin_name:
        errors.append("Admin name is required")
    if not admin_email:
        errors.append("Admin email is required")
    if not admin_password or len(admin_password) < 6:
        errors.append("Password must be at least 6 characters")

    if Institution.query.filter_by(subdomain=subdomain).first():
        errors.append("Subdomain already exists")
    if User.query.filter_by(email=admin_email).first():
        errors.append("Email already registered")

    if errors:
        return {"errors": errors}, 400

    try:
        institution = Institution(name=name, subdomain=subdomain, status="Active", created_at=utc_now())
        db.session.add(institution)
        db.session.flush()

        admin = User(
            institution_id=institution.id,
            email=admin_email,
            role="institution_admin",
            full_name=admin_name,
            phone_number=admin_phone,
            is_active=True,
        )
        admin.set_password(admin_password)
        db.session.add(admin)

        period = datetime.utcnow().strftime("%Y-%m")
        billing = BillingRecord(
            institution_id=institution.id,
            billing_period=period,
            saas_flat_fee=5000.00,
            sms_count=0,
            sms_unit_price=2.50,
            total_amount_due=5000.00,
            payment_status="Pending",
        )
        db.session.add(billing)
        db.session.commit()

        return {
            "institution": institution.to_dict(),
            "admin": admin.to_dict(),
        }, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to register institution"]}, 500


def register_user(data, creator):
    role = data.get("role")
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()
    phone_number = (data.get("phone_number") or "").strip()

    allowed_roles = {
        "institution_admin": ["teacher", "student", "parent"],
        "super_admin": ["institution_admin", "teacher", "student", "parent"],
    }

    if creator.role not in allowed_roles or role not in allowed_roles[creator.role]:
        return {"errors": ["Cannot create this role"]}, 403

    institution_id = creator.institution_id
    if creator.role == "super_admin" and role == "institution_admin":
        institution_id = data.get("institution_id")
        if not institution_id:
            return {"errors": ["institution_id is required"]}, 400

    if not email or not password or not full_name:
        return {"errors": ["Email, password, and full name are required"]}, 400

    if User.query.filter_by(email=email).first():
        return {"errors": ["Email already registered"]}, 400

    try:
        user = User(
            institution_id=institution_id,
            email=email,
            role=role,
            full_name=full_name,
            phone_number=phone_number,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return {"user": user.to_dict()}, 201
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to register user"]}, 500
