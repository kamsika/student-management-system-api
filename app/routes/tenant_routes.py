from flask import Blueprint, request

from app.controllers.tenant_controller import resolve_tenant

tenant_bp = Blueprint("tenant", __name__, url_prefix="/api/tenant")


@tenant_bp.get("/resolve")
def resolve():
    subdomain = request.args.get("subdomain", "")
    result, status = resolve_tenant({"subdomain": subdomain})
    return result, status
