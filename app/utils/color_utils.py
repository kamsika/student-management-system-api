import re

DEFAULT_PRIMARY_COLOR = "#0047AB"
DEFAULT_SECONDARY_COLOR = "#FFFFFF"
DEFAULT_ACCENT_COLOR = "#F9BF15"

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
SHORT_HEX_PATTERN = re.compile(r"^#([0-9A-Fa-f]{3})$")

NAMED_COLOR_HEX = {
    "white": "#FFFFFF",
    "black": "#000000",
    "blue": "#2563EB",
    "red": "#EF4444",
    "green": "#22C55E",
    "yellow": "#FACC15",
}


def is_valid_hex_color(value) -> bool:
    if value is None:
        return False
    return bool(HEX_COLOR_PATTERN.match(str(value).strip()))


def normalize_hex_color(value, fallback=DEFAULT_PRIMARY_COLOR) -> str:
    safe_fallback = (
        str(fallback).strip().upper()
        if is_valid_hex_color(fallback)
        else DEFAULT_PRIMARY_COLOR
    )

    if value is None:
        return safe_fallback

    text = str(value).strip()
    if not text or text.lower() == "transparent":
        return safe_fallback

    if is_valid_hex_color(text):
        return text.upper()

    short = SHORT_HEX_PATTERN.match(text)
    if short:
        r, g, b = short.group(1)
        return f"#{r}{r}{g}{g}{b}{b}".upper()

    named = NAMED_COLOR_HEX.get(text.lower())
    if named:
        return named

    return safe_fallback


def normalize_institution_colors(institution) -> None:
    institution.primary_color = normalize_hex_color(
        institution.primary_color,
        DEFAULT_PRIMARY_COLOR,
    )
    institution.secondary_color = normalize_hex_color(
        institution.secondary_color,
        DEFAULT_SECONDARY_COLOR,
    )
    institution.accent_color = normalize_hex_color(
        institution.accent_color,
        DEFAULT_ACCENT_COLOR,
    )
