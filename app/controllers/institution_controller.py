from datetime import datetime

from app.extensions import db
from app.models import BillingRecord, Institution


def create_institution(data):
    name = (data.get("name") or "").strip()
    subdomain = (data.get("subdomain") or "").strip().lower()

    if not name or not subdomain:
        return {"errors": ["Name and subdomain are required"]}, 400

    if Institution.query.filter_by(subdomain=subdomain).first():
        return {"errors": ["Subdomain already exists"]}, 400

    try:
        institution = Institution(name=name, subdomain=subdomain, status="Active")
        db.session.add(institution)
        db.session.flush()

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
        return {"institution": institution.to_dict()}, 201
    except Exception:
        db.session.rollback()
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
