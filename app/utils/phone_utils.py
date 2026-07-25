"""Phone number normalization shared by parent login and seeding."""


def digits_only(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def phone_matches(stored_phone, input_phone) -> bool:
    """Compare phone numbers ignoring formatting (+, spaces, dashes)."""
    stored = digits_only(stored_phone)
    given = digits_only(input_phone)
    if not stored or not given:
        return False
    if stored == given:
        return True

    shorter, longer = (stored, given) if len(stored) <= len(given) else (given, stored)
    if len(shorter) >= 9 and longer.endswith(shorter):
        return True

    if len(stored) >= 9 and len(given) >= 9 and stored[-9:] == given[-9:]:
        return True
    return False


def mask_phone(value) -> str:
    digits = digits_only(value)
    if not digits:
        return "<empty>"
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"
