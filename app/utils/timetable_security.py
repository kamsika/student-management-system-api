"""RBAC + tenant helpers for Timetable Auto-Marking endpoints."""

from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt, verify_jwt_in_request

from app.models import User

# Roles allowed to create/update/delete timetable slots.
TIMETABLE_WRITE_ROLES = ("institution_admin", "teacher", "super_admin")
# Roles allowed to read timetable slots (still tenant-scoped).
TIMETABLE_READ_ROLES = (
    "institution_admin",
    "teacher",
    "student",
    "parent",
    "super_admin",
)


def get_session_identity():
    """Return role + tenantId from the JWT (with DB user fallback)."""
    verify_jwt_in_request()
    claims = get_jwt()
    user_id = claims.get("sub")
    user = User.query.get(int(user_id)) if user_id is not None else None

    role = claims.get("role") or (user.role if user else None)
    # Prefer claim, fall back to user.institution_id for older tokens.
    tenant_id = claims.get("institution_id")
    if tenant_id is None and user is not None:
        tenant_id = user.institution_id
    if tenant_id is not None:
        try:
            tenant_id = int(tenant_id)
        except (TypeError, ValueError):
            tenant_id = None

    return {
        "user": user,
        "user_id": int(user_id) if user_id is not None else None,
        "role": role,
        "tenant_id": tenant_id,
        "tenantId": tenant_id,
    }


def require_timetable_write(fn):
    """Block students/parents from POST/DELETE timetable mutations."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        identity = get_session_identity()
        role = identity.get("role")
        if role not in TIMETABLE_WRITE_ROLES:
            return jsonify({"errors": ["Only admin or teacher can modify timetables"]}), 403
        if role != "super_admin" and not identity.get("tenant_id"):
            return jsonify({"errors": ["User is not linked to a tenant/center"]}), 400
        return fn(*args, **kwargs)

    return wrapper


def require_timetable_read(fn):
    """Allow admin/teacher/student/parent reads; still require a tenant for non-super admins."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        identity = get_session_identity()
        role = identity.get("role")
        if role not in TIMETABLE_READ_ROLES:
            return jsonify({"errors": ["Insufficient permissions"]}), 403
        if role != "super_admin" and not identity.get("tenant_id"):
            return jsonify({"errors": ["User is not linked to a tenant/center"]}), 400
        return fn(*args, **kwargs)

    return wrapper


def assert_same_tenant(resource_tenant_id, identity):
    """Return an error payload when a resource belongs to another tenant."""
    if identity.get("role") == "super_admin":
        return None, None
    tenant_id = identity.get("tenant_id")
    if tenant_id is None:
        return {"errors": ["User is not linked to a tenant/center"]}, 400
    if resource_tenant_id is None or int(resource_tenant_id) != int(tenant_id):
        return {"errors": ["Access denied: tenant mismatch"]}, 403
    return None, None


def tenant_scoped_timetable_query(query, model, identity):
    """Force every non-super-admin query to the caller's tenantId."""
    if identity.get("role") == "super_admin":
        return query
    return query.filter(model.tenant_id == identity["tenant_id"])
