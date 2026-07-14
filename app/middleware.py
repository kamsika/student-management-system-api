from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt, verify_jwt_in_request

from app.models import User


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            user_role = claims.get("role")
            if user_role not in roles:
                return jsonify({"errors": ["Insufficient permissions"]}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def get_current_user():
    verify_jwt_in_request()
    claims = get_jwt()
    user_id = claims.get("sub")
    return User.query.get(int(user_id))


def tenant_filter_query(query, model, user):
    if user.role == "super_admin":
        return query
    if hasattr(model, "institution_id"):
        return query.filter(model.institution_id == user.institution_id)
    return query
