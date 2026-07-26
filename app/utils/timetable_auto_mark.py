"""Timetable-based auto-marking helpers for kiosk / QR attendance scans."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_

from app.models import Timetable
from app.utils import APP_TIMEZONE, get_app_tz, local_now

# A scan can count for a class that starts within this many minutes.
UPCOMING_WINDOW_MINUTES = 10
# Back-to-back classes: the next class must start exactly when the current one
# ends. A real break means the later class requires its own scan.
CONTINUOUS_GAP_MINUTES = 0

_VALID_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def normalize_day_name(value: Optional[str]) -> Optional[str]:
    """Return canonical weekday name (Monday…) or None."""
    text = str(value or "").strip()
    if not text:
        return None
    for day in _VALID_DAYS:
        if day.lower() == text.lower():
            return day
    return None


def time_to_minutes(value) -> int:
    """
    Convert a timetable/system time string into minutes from midnight.

    Supports:
      - 24-hour: "09:15", "9:15", "09:15:00"
      - 12-hour: "9:15 AM", "09:15PM", "9:15 a.m."
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("empty time value")

    upper = raw.upper().replace(".", "")
    is_am = bool(re.search(r"\bAM\b", upper)) or upper.endswith("AM")
    is_pm = bool(re.search(r"\bPM\b", upper)) or upper.endswith("PM")

    cleaned = re.sub(r"[^0-9:]", "", upper)
    if not cleaned:
        raise ValueError(f"unrecognized time value: {raw!r}")

    parts = [part for part in cleaned.split(":") if part != ""]
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    if is_am or is_pm:
        if hour < 1 or hour > 12:
            raise ValueError(f"invalid 12-hour clock value: {raw!r}")
        hour = hour % 12
        if is_pm:
            hour += 12
    elif hour > 23 or minute > 59:
        raise ValueError(f"invalid 24-hour clock value: {raw!r}")

    if minute < 0 or minute > 59:
        raise ValueError(f"invalid minutes in time value: {raw!r}")

    return hour * 60 + minute


def format_hhmm(now: Optional[datetime] = None) -> str:
    now = now or local_now()
    return f"{now.hour:02d}:{now.minute:02d}"


def minutes_to_hhmm(total_minutes: int) -> str:
    total_minutes = int(total_minutes) % (24 * 60)
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


def current_day_of_week(now: Optional[datetime] = None) -> str:
    now = now or local_now()
    return now.strftime("%A")


def current_minutes(now: Optional[datetime] = None) -> int:
    now = now or local_now()
    return now.hour * 60 + now.minute


def _unique_slots(slots):
    seen = set()
    unique = []
    for slot in slots:
        try:
            start_key = minutes_to_hhmm(time_to_minutes(slot.start_time))
            end_key = minutes_to_hhmm(time_to_minutes(slot.end_time))
        except ValueError:
            start_key = str(slot.start_time)
            end_key = str(slot.end_time)
        key = (slot.subject_name.strip().lower(), start_key, end_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(slot)
    return unique


def _slot_debug_dict(slot):
    try:
        start_mins = time_to_minutes(slot.start_time)
        end_mins = time_to_minutes(slot.end_time)
        start_norm = minutes_to_hhmm(start_mins)
        end_norm = minutes_to_hhmm(end_mins)
    except ValueError as exc:
        start_mins = end_mins = None
        start_norm = str(slot.start_time)
        end_norm = str(slot.end_time)
        parse_error = str(exc)
    else:
        parse_error = None

    return {
        "id": slot.id,
        "day": slot.day_of_week,
        "subject": slot.subject_name,
        "startTime": slot.start_time,
        "endTime": slot.end_time,
        "startMinutes": start_mins,
        "endMinutes": end_mins,
        "startNormalized": start_norm,
        "endNormalized": end_norm,
        "classroomId": slot.classroom_id,
        "studentId": slot.student_id,
        "parseError": parse_error,
    }


def fetch_student_day_slots(
    student_id: int,
    *,
    classroom_id: Optional[int] = None,
    day_of_week: Optional[str] = None,
):
    """
    Fetch today's timetable slots for a student.

    - Day match is case-insensitive (Sunday == sunday).
    - When classroom_id is provided, only slots for that classroom are returned.
    - Prefer student-specific rows; fall back to classroom-wide slots.
    """
    day = normalize_day_name(day_of_week) or current_day_of_week()
    day_key = day.lower()

    query = Timetable.query.filter(func.lower(Timetable.day_of_week) == day_key)
    if classroom_id is not None:
        query = query.filter(Timetable.classroom_id == int(classroom_id))

    student_slots = (
        query.filter(Timetable.student_id == student_id)
        .order_by(Timetable.start_time.asc(), Timetable.id.asc())
        .all()
    )
    if student_slots:
        print(
            f"[TIMETABLE] Using student-specific slots "
            f"studentId={student_id} classroomId={classroom_id} day={day!r} "
            f"count={len(student_slots)}"
        )
        return _unique_slots(student_slots)

    if classroom_id is not None:
        classroom_slots = (
            query.filter(
                or_(Timetable.student_id.is_(None), Timetable.student_id == student_id)
            )
            .order_by(Timetable.start_time.asc(), Timetable.id.asc())
            .all()
        )
        print(
            f"[TIMETABLE] Falling back to classroom slots "
            f"classroomId={classroom_id} day={day!r} count={len(classroom_slots)}"
        )
        return _unique_slots(classroom_slots)

    print(
        f"[TIMETABLE] No slots found studentId={student_id} "
        f"classroomId={classroom_id} day={day!r}"
    )
    return []


def find_current_class(slots, now_minutes: Optional[int] = None):
    """Pick the class in progress, or the next class starting within the upcoming window."""
    now_minutes = current_minutes() if now_minutes is None else now_minutes
    in_progress = []
    upcoming = []

    for slot in slots:
        try:
            start = time_to_minutes(slot.start_time)
            end = time_to_minutes(slot.end_time)
        except ValueError as exc:
            print(
                f"[TIMETABLE] Skipping slot id={getattr(slot, 'id', None)} "
                f"bad time parse: {exc}"
            )
            continue

        if start <= now_minutes <= end:
            in_progress.append(slot)
            print(
                f"[TIMETABLE] IN PROGRESS subject={slot.subject_name!r} "
                f"{minutes_to_hhmm(start)}-{minutes_to_hhmm(end)} "
                f"(mins {start}-{end}, now={now_minutes})"
            )
        elif 0 <= start - now_minutes <= UPCOMING_WINDOW_MINUTES:
            upcoming.append(slot)
            print(
                f"[TIMETABLE] UPCOMING subject={slot.subject_name!r} "
                f"{minutes_to_hhmm(start)}-{minutes_to_hhmm(end)} "
                f"starts_in={start - now_minutes}m"
            )

    if in_progress:
        return max(in_progress, key=lambda s: time_to_minutes(s.start_time))
    if upcoming:
        return min(upcoming, key=lambda s: time_to_minutes(s.start_time))
    return None


def collect_continuous_classes(slots, current_slot):
    """Return the current class and directly adjacent following classes.

    This is intentionally based on the timetable boundary rather than a broad
    time window. For example, 15:00-16:00 followed by 16:00-17:00 is one scan
    chain, while 15:00-16:00 followed by 17:00-18:00 is two separate chains.
    """
    if current_slot is None:
        return []

    def _sort_key(slot):
        try:
            return (time_to_minutes(slot.start_time), slot.id)
        except ValueError:
            return (10**9, slot.id)

    ordered = sorted(slots, key=_sort_key)
    try:
        index = next(i for i, slot in enumerate(ordered) if slot.id == current_slot.id)
    except StopIteration:
        return [current_slot]

    selected = [ordered[index]]
    cursor = index
    while cursor + 1 < len(ordered):
        current = ordered[cursor]
        nxt = ordered[cursor + 1]
        try:
            gap = time_to_minutes(nxt.start_time) - time_to_minutes(current.end_time)
        except ValueError:
            break
        # Overlapping slots are not treated as a continuous chain: there is no
        # unambiguous class transition at which to carry attendance forward.
        if gap == CONTINUOUS_GAP_MINUTES:
            print(
                f"[TIMETABLE] Continuous class linked "
                f"{current.subject_name!r} -> {nxt.subject_name!r} gap={gap}m"
            )
            selected.append(nxt)
            cursor += 1
            continue
        break

    return selected


def resolve_auto_mark_subjects(
    student_id: int,
    *,
    classroom_id: Optional[int] = None,
    enrolled_subjects: Optional[list] = None,
    now: Optional[datetime] = None,
):
    """
    Resolve which subject names should be marked Present for this scan.

    Rules:
    1. Load today's timetable for the student (currentDay, local timezone).
    2. Pick the slot active at the current local time (+ continuous following classes).
    3. Only enrolled subjects are markable when the student has an enrollment list.
       An unenrolled upcoming class is reported as a warning instead of blocking
       the current enrolled class.
    """
    now = now or local_now()
    # Ensure comparisons always use app-local wall clock (IST / Asia/Colombo by default).
    if now.tzinfo is not None:
        now = now.astimezone(get_app_tz()).replace(tzinfo=None)

    day = current_day_of_week(now)
    day_canonical = normalize_day_name(day) or day
    now_minutes = current_minutes(now)
    current_time = format_hhmm(now)

    print("=" * 60)
    print("[TIMETABLE] Attendance scan matching")
    print(f"[TIMETABLE] timezone={APP_TIMEZONE}")
    print(f"[TIMETABLE] currentDay={day_canonical!r}")
    print(f"[TIMETABLE] currentTime={current_time} (local HH:mm)")
    print(f"[TIMETABLE] currentMinutesFromMidnight={now_minutes}")
    print(f"[TIMETABLE] studentId={student_id} classroomId={classroom_id}")

    slots = fetch_student_day_slots(
        student_id,
        classroom_id=classroom_id,
        day_of_week=day_canonical,
    )

    slot_debug = [_slot_debug_dict(slot) for slot in slots]
    print(f"[TIMETABLE] fetchedTimetableEntriesToday count={len(slot_debug)}")
    for entry in slot_debug:
        print(
            "[TIMETABLE]   entry "
            f"id={entry['id']} day={entry['day']!r} subject={entry['subject']!r} "
            f"raw={entry['startTime']}-{entry['endTime']} "
            f"normalized={entry['startNormalized']}-{entry['endNormalized']} "
            f"mins={entry['startMinutes']}-{entry['endMinutes']} "
            f"classroomId={entry['classroomId']} studentId={entry['studentId']}"
            + (f" parseError={entry['parseError']}" if entry["parseError"] else "")
        )

    enrolled = [str(name).strip() for name in (enrolled_subjects or []) if str(name).strip()]
    enrolled_keys = {name.lower() for name in enrolled}
    print(f"[TIMETABLE] enrolledSubjects={enrolled}")

    display_slots = slots

    if not slots:
        print("[TIMETABLE] No timetable rows for today/classroom — nothing to mark")
        print("=" * 60)
        return {
            "dayOfWeek": day_canonical,
            "currentTime": current_time,
            "currentMinutes": now_minutes,
            "timezone": APP_TIMEZONE,
            "slots": [],
            "eligibleSlots": [],
            "subjects": [],
            "currentSlot": None,
            "enrolledSubjects": enrolled,
        }

    current = find_current_class(slots, now_minutes=now_minutes)
    if current is None:
        print(
            f"[TIMETABLE] No active/upcoming slot at {current_time} "
            f"({now_minutes} mins from midnight)"
        )
    else:
        print(
            f"[TIMETABLE] Selected current slot subject={current.subject_name!r} "
            f"{current.start_time}-{current.end_time}"
        )

    eligible = collect_continuous_classes(slots, current)

    unenrolled_subjects = []
    seen_unenrolled = set()
    for slot in eligible:
        subject = str(slot.subject_name or "").strip()
        subject_key = subject.lower()
        if subject and subject_key not in enrolled_keys and subject_key not in seen_unenrolled:
            seen_unenrolled.add(subject_key)
            unenrolled_subjects.append(subject)

    markable_slots = (
        [slot for slot in eligible if slot.subject_name.strip().lower() in enrolled_keys]
        if enrolled_keys
        else eligible
    )
    current_is_markable = bool(
        current
        and (
            not enrolled_keys
            or current.subject_name.strip().lower() in enrolled_keys
        )
    )
    warning = None
    if unenrolled_subjects:
        warning = (
            f"Student is not enrolled for {', '.join(unenrolled_subjects)}. "
            "Those classes are excluded from attendance."
        )
        print(f"[TIMETABLE] Unenrolled classes excluded: {unenrolled_subjects}")

    # The current class is marked immediately. Upcoming continuous classes are
    # returned separately so an authorized user can confirm or untick them.
    subjects = [current.subject_name] if current_is_markable else []
    print(f"[TIMETABLE] subjectsToMark={subjects}")
    print("=" * 60)

    return {
        "dayOfWeek": day_canonical,
        "currentTime": current_time,
        "currentMinutes": now_minutes,
        "timezone": APP_TIMEZONE,
        "slots": display_slots if enrolled_keys else slots,
        "eligibleSlots": markable_slots,
        "continuousSlots": eligible,
        "markableSlots": markable_slots,
        "subjects": subjects,
        "currentSlot": current,
        "enrolledSubjects": enrolled,
        "blocked": bool(current and not current_is_markable),
        "unenrolledSubjects": unenrolled_subjects,
        "enrollmentWarning": warning,
    }
