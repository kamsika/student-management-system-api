import urllib.error
import urllib.request
from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models import BillingRecord, SmsLog
from app.utils import utc_now


def get_active_billing_record(institution_id):
    period = datetime.utcnow().strftime("%Y-%m")
    record = BillingRecord.query.filter_by(
        institution_id=institution_id,
        billing_period=period,
    ).first()
    if not record:
        record = BillingRecord(
            institution_id=institution_id,
            billing_period=period,
            saas_flat_fee=current_app.config["SAAS_FLAT_FEE"],
            sms_count=0,
            sms_unit_price=current_app.config["SMS_UNIT_PRICE"],
            total_amount_due=current_app.config["SAAS_FLAT_FEE"],
            payment_status="Pending",
        )
        record.recalculate_total()
        db.session.add(record)
        db.session.flush()
    return record


def increment_sms_billing(institution_id):
    record = get_active_billing_record(institution_id)
    record.sms_count += 1
    record.recalculate_total()
    db.session.add(record)


def dispatch_sms(institution_id, recipient_phone, message_body):
    if not recipient_phone:
        log = SmsLog(
            institution_id=institution_id,
            recipient_phone=recipient_phone or "unknown",
            message_body=message_body,
            status="Failed",
            error_details="No recipient phone number",
            sent_at=utc_now(),
        )
        db.session.add(log)
        return log

    status = "Sent"
    error_details = None
    gateway_url = current_app.config.get("SMS_GATEWAY_URL")
    gateway_key = current_app.config.get("SMS_GATEWAY_API_KEY")

    if gateway_url and gateway_key:
        try:
            payload = f"phone={recipient_phone}&message={message_body}&key={gateway_key}".encode("utf-8")
            req = urllib.request.Request(gateway_url, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    status = "Delivered"
                else:
                    status = "Failed"
                    error_details = f"Gateway returned status {response.status}"
        except urllib.error.URLError as exc:
            status = "Failed"
            error_details = str(exc)
    else:
        status = "Delivered"

    log = SmsLog(
        institution_id=institution_id,
        recipient_phone=recipient_phone,
        message_body=message_body,
        status=status,
        error_details=error_details,
        sent_at=utc_now(),
    )
    db.session.add(log)
    increment_sms_billing(institution_id)
    return log
