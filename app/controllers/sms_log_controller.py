from app.models import SmsLog


def list_sms_logs(user):
    query = SmsLog.query

    if user.role == "institution_admin":
        query = query.filter_by(institution_id=user.institution_id)
    elif user.role == "super_admin":
        pass
    else:
        return {"errors": ["Access denied"]}, 403

    logs = query.order_by(SmsLog.sent_at.desc()).limit(200).all()
    return {"sms_logs": [log.to_dict() for log in logs]}, 200
