from datetime import datetime

from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models import BillingRecord, Institution, User
from app.utils import utc_now
from app.utils.institution_admin_utils import generate_admin_password, generate_unique_admin_email


def create_institution(data):
    """Create a tuition center and a default institution admin account.

    Super Admin can optionally pass admin_name / admin_email / admin_phone.
    If email is omitted, one is generated. A temporary password is always
    generated and returned once in admin_credentials for sharing with the
    center owner.
    """
    name = (data.get("name") or "").strip()
    subdomain = (data.get("subdomain") or "").strip().lower()
    admin_name = (data.get("admin_name") or "").strip()
    admin_email = (data.get("admin_email") or "").strip().lower()
    admin_phone = (data.get("admin_phone") or "").strip()

    if not name or not subdomain:
        return {"errors": ["Name and subdomain are required"]}, 400

    if not all(c.isalnum() or c == "-" for c in subdomain):
        return {"errors": ["Subdomain must contain only letters, numbers, and hyphens"]}, 400

    if Institution.query.filter_by(subdomain=subdomain).first():
        return {"errors": ["Subdomain already exists"]}, 400

    if admin_email and User.query.filter_by(email=admin_email).first():
        return {"errors": ["Admin email already registered"]}, 400

    saas_flat_fee = float(current_app.config.get("SAAS_FLAT_FEE", 5000.00))
    sms_unit_price = float(current_app.config.get("SMS_UNIT_PRICE", 2.50))

    try:
        institution = Institution(
            name=name,
            subdomain=subdomain,
            status="Active",
            created_at=utc_now(),
        )
        db.session.add(institution)
        db.session.flush()

        generated_email = admin_email or generate_unique_admin_email(subdomain)
        generated_password = generate_admin_password()
        resolved_admin_name = admin_name or f"{name} Admin"

        # Default center admin linked to this institution (role used by the app).
        admin = User(
            institution_id=institution.id,
            email=generated_email.lower(),
            role="institution_admin",
            full_name=resolved_admin_name,
            phone_number=admin_phone or None,
            is_active=True,
        )
        admin.set_password(generated_password)

        # Round-trip check before commit so a bad hash never gets saved.
        if not admin.check_password(generated_password):
            db.session.rollback()
            print("[INSTITUTION] Password hash verification failed after set_password")
            return {"errors": ["Failed to hash admin password"]}, 500

        if not admin.is_active:
            admin.is_active = True

        db.session.add(admin)
        print(
            f"[INSTITUTION] Creating admin email={admin.email!r} "
            f"is_active={admin.is_active} hash_len={len(admin.password or '')} "
            f"hash_prefix={str(admin.password)[:24]!r}"
        )

        period = datetime.utcnow().strftime("%Y-%m")
        billing = BillingRecord(
            institution_id=institution.id,
            billing_period=period,
            saas_flat_fee=saas_flat_fee,
            sms_count=0,
            sms_unit_price=sms_unit_price,
            total_amount_due=saas_flat_fee,
            payment_status="Pending",
        )
        db.session.add(billing)
        db.session.commit()

        # Re-load from DB and verify the stored hash still matches.
        saved_admin = User.query.filter(func.lower(User.email) == generated_email.lower()).first()
        if not saved_admin or not saved_admin.check_password(generated_password):
            print(
                f"[INSTITUTION] Post-commit password verify failed "
                f"found={bool(saved_admin)} email={generated_email!r}"
            )
            return {"errors": ["Admin was created but password verification failed"]}, 500

        print(
            f"[INSTITUTION] Admin ready user_id={saved_admin.id} email={saved_admin.email!r} "
            f"is_active={saved_admin.is_active}"
        )

        return {
            "institution": institution.to_dict(),
            "admin": saved_admin.to_dict(),
            "admin_credentials": {
                "email": generated_email,
                "password": generated_password,
                "full_name": resolved_admin_name,
                "role": "institution_admin",
                "institution_id": institution.id,
            },
        }, 201
    except Exception as exc:
        db.session.rollback()
        print(f"[INSTITUTION] create_institution failed: {exc}")
        return {"errors": ["Failed to create institution"]}, 500


def list_institutions():
    institutions = Institution.query.order_by(Institution.created_at.desc()).all()
    return {"institutions": [i.to_dict() for i in institutions]}, 200


def update_institution_status(institution_id, data):
    institution = Institution.query.get(institution_id)
    if not institution:
        return {"errors": ["Institution not found"]}, 404

    status = data.get("status")
    if status not in ("Active", "Suspended"):
        return {"errors": ["Invalid status"]}, 400

    institution.status = status
    db.session.commit()
    return {"institution": institution.to_dict()}, 200


def get_institution_billing(institution_id, user):
    if user.role == "institution_admin" and user.institution_id != institution_id:
        return {"errors": ["Access denied"]}, 403

    records = BillingRecord.query.filter_by(institution_id=institution_id).order_by(
        BillingRecord.billing_period.desc()
    ).all()

    if not records:
        return {"errors": ["No billing records found"]}, 404

    return {"billing_records": [r.to_dict() for r in records]}, 200
