from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import os

from dotenv import load_dotenv

load_dotenv()

# Default to Sri Lanka time; override with APP_TIMEZONE=Asia/Kolkata if needed.
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Colombo")


def get_app_tz() -> ZoneInfo:
    try:
        return ZoneInfo(APP_TIMEZONE)
    except Exception:
        return ZoneInfo("Asia/Colombo")


def utc_now() -> datetime:
    """Timezone-naive UTC timestamp for DB storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    """Current time in the configured app timezone (naive local wall clock)."""
    return datetime.now(get_app_tz()).replace(tzinfo=None)


def local_today() -> date:
    """Calendar date in the configured app timezone."""
    return datetime.now(get_app_tz()).date()


def parse_attendance_date(raw_value):
    """Parse YYYY-MM-DD into a date, or return local_today() when empty.

    Returns (date, None) on success, or (None, error_message) on failure.
    """
    if raw_value is None or str(raw_value).strip() == "":
        return local_today(), None
    try:
        return date.fromisoformat(str(raw_value).strip()), None
    except ValueError:
        return None, "date must be YYYY-MM-DD"


def to_iso(value):
    """Serialize datetimes as ISO-8601 with explicit UTC Z suffix when naive."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Stored values are treated as UTC.
            return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def parse_incoming_timestamp(raw_value) -> datetime:
    """Parse client/server timestamps into naive UTC for storage."""
    if raw_value is None or raw_value == "":
        return utc_now()

    try:
        text = str(raw_value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        # Naive values from older clients: treat as UTC wall clock.
        return parsed
    except (TypeError, ValueError):
        return utc_now()
