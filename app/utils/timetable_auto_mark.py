"""Timetable-based auto-marking helpers for kiosk / QR attendance scans."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import or_

from app.models import Timetable
from app.utils import local_now

# A scan can count for a class that starts within this many minutes.
UPCOMING_WINDOW_MINUTES = 10
# Back-to-back classes: next start - current end <= this gap → auto-mark both.
CONTINUOUS_GAP_MINUTES = 15


def _time_to_minutes(value: str) -> int:
    text = str(value or "").strip()
    if len(text) >= 5:
        text = text[:5]
    hour, minute = text.split(":")
    return int(hour) * 60 + int(minute)


def current_day_of_week(now: Optional[datetime] = None) -> str:
    now = now or local_now()
    return now.strftime("%A")


def current_minutes(now: Optional[datetime] = None) -> int:
    now = now or local_now()
    return now.hour * 60 + now.minute


def fetch_student_day_slots(
    student_id: int,
    *,
    classroom_id: Optional[int] = None,
    day_of_week: Optional[str] = None,
):
    """Fetch timetable slots for a student on the given weekday."""
    day = day_of_week or current_day_of_week()
    clauses = [Timetable.student_id == student_id]
    if classroom_id is not None:
        clauses.append(Timetable.classroom_id == classroom_id)

    slots = (
        Timetable.query.filter(Timetable.day_of_week == day)
        .filter(or_(*clauses))
        .order_by(Timetable.start_time.asc(), Timetable.id.asc())
        .all()
    )

    seen = set()
    unique = []
    for slot in slots:
        key = (slot.subject_name.strip().lower(), slot.start_time[:5], slot.end_time[:5])
        if key in seen:
            continue
        seen.add(key)
        unique.append(slot)
    return unique


def find_current_class(slots, now_minutes: Optional[int] = None):
    """Pick the class in progress, or the next class starting within the upcoming window."""
    now_minutes = current_minutes() if now_minutes is None else now_minutes
    in_progress = []
    upcoming = []

    for slot in slots:
        start = _time_to_minutes(slot.start_time)
        end = _time_to_minutes(slot.end_time)
        if start <= now_minutes <= end:
            in_progress.append(slot)
        elif 0 <= start - now_minutes <= UPCOMING_WINDOW_MINUTES:
            upcoming.append(slot)

    if in_progress:
        return max(in_progress, key=lambda s: _time_to_minutes(s.start_time))
    if upcoming:
        return min(upcoming, key=lambda s: _time_to_minutes(s.start_time))
    return None


def collect_continuous_classes(slots, current_slot):
    """Return [current, ...following] while each next gap is <= CONTINUOUS_GAP_MINUTES."""
    if current_slot is None:
        return []

    ordered = sorted(slots, key=lambda s: (_time_to_minutes(s.start_time), s.id))
    try:
        index = next(i for i, slot in enumerate(ordered) if slot.id == current_slot.id)
    except StopIteration:
        return [current_slot]

    selected = [ordered[index]]
    cursor = index
    while cursor + 1 < len(ordered):
        current = ordered[cursor]
        nxt = ordered[cursor + 1]
        gap = _time_to_minutes(nxt.start_time) - _time_to_minutes(current.end_time)
        if gap < 0 or gap <= CONTINUOUS_GAP_MINUTES:
            selected.append(nxt)
            cursor += 1
            continue
        break

    return selected


def resolve_auto_mark_subjects(
    student_id: int,
    *,
    classroom_id: Optional[int] = None,
    now: Optional[datetime] = None,
):
    """Resolve which subject names should be auto-marked Present for this scan."""
    now = now or local_now()
    day = current_day_of_week(now)
    now_minutes = current_minutes(now)
    slots = fetch_student_day_slots(student_id, classroom_id=classroom_id, day_of_week=day)
    if not slots:
        return {
            "dayOfWeek": day,
            "currentTime": f"{now.hour:02d}:{now.minute:02d}",
            "slots": [],
            "eligibleSlots": [],
            "subjects": [],
            "currentSlot": None,
        }

    current = find_current_class(slots, now_minutes=now_minutes)
    eligible = collect_continuous_classes(slots, current)
    subjects = [slot.subject_name for slot in eligible]

    return {
        "dayOfWeek": day,
        "currentTime": f"{now.hour:02d}:{now.minute:02d}",
        "slots": slots,
        "eligibleSlots": eligible,
        "subjects": subjects,
        "currentSlot": current,
    }
