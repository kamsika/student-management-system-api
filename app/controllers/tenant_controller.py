from app.models import Institution


def resolve_tenant(data):
    """Public lookup of an institution by subdomain (path slug)."""
    subdomain = (data.get("subdomain") or "").strip().lower()
    if not subdomain:
        return {"tenant": None, "subdomain": None}, 200

    institution = Institution.query.filter_by(subdomain=subdomain).first()
    if not institution:
        return {
            "tenant": None,
            "subdomain": subdomain,
            "code": "institution_not_found",
            "errors": ["Institution not found"],
        }, 404

    if institution.status == "Suspended":
        return {
            "tenant": institution.to_dict(),
            "subdomain": subdomain,
            "code": "institution_suspended",
            "errors": ["Institution is suspended"],
        }, 403

    return {"tenant": institution.to_dict(), "subdomain": subdomain}, 200
