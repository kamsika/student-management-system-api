"""Timetable-based auto-marking helpers for kiosk / QR attendance scans."""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Optional

from sqlalchemy import func, or_

from app.models import Timetable
from app.utils import APP_TIMEZONE, get_app_tz, local_now

# A scan can count for a class that starts within this many minutes.
UPCOMING_WINDOW_MINUTES = 10
# Back-to-back classes: next start - current end <= this gap → auto-mark both.
CONTINUOUS_GAP_MINUTES = 15

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
    """Return canonical weekday name (Monday…) with case-insensitive match."""
    text = str(value or "").strip()
    if not text:
        return None
    for day in _VALID_DAYS:
        if day.lower() == text.lower():
            return day
    return None


def time_to_minutes(value) -> int:
    """
    Convert a timetable/system time into minutes from midnight.

    Examples:
      "09:15" / "9:15" / "09:15:00" → 555
      "9:15 AM" / "09:15AM" → 555
      "1:30 PM" → 810

    Supports datetime.time / datetime.datetime as well.
    """
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, time):
        return value.hour * 60 + value.minute

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("empty time value")

    # Normalize unicode spaces and common AM/PM variants.
    upper = (
        raw.upper()
        .replace("\u00a0", " ")
        .replace(".", "")
        .replace("Ａ", "A")
        .replace("Ｐ", "P")
        .replace("Ｍ", "M")
    )
    upper = re.sub(r"\s+", " ", upper).strip()

    is_am = bool(re.search(r"(?:^|\s)AM$", upper)) or upper.endswith(" AM") or bool(
        re.search(r"\dAM$", upper.replace(" ", ""))
    )
    is_pm = bool(re.search(r"(?:^|\s)PM$", upper)) or upper.endswith(" PM") or bool(
        re.search(r"\dPM$", upper.replace(" ", ""))
    )
    # Compact forms like "9:15AM"
    compact = upper.replace(" ", "")
    if compact.endswith("AM"):
        is_am = True
    if compact.endswith("PM"):
        is_pm = True

    cleaned = re.sub(r"[^0-9:]", "", upper)
    if not cleaned:
        raise ValueError(f"unrecognized time value: {raw!r}")

    parts = [part for part in cleaned.split(":") if part != ""]
    if not parts:
        raise ValueError(f"unrecognized time value: {raw!r}")

    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0

    if minute < 0 or minute > 59:
        raise ValueError(f"invalid minutes in time value: {raw!r}")

    if is_am or is_pm:
        if hour < 1 or hour > 12:
            raise ValueError(f"invalid 12-hour clock value: {raw!r}")
        hour = hour % 12
        if is_pm:
            hour += 12
    else:
        if hour > 23:
            raise ValueError(f"invalid 24-hour clock value: {raw!r}")

    return hour * 60 + minute


def format_hhmm(now: Optional[datetime] = None) -> str:
    """Local wall-clock HH:mm (app timezone)."""
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
    """Minutes from midnight in the app-local timezone."""
    now = now or local_now()
    return now.hour * 60 + now.minute


def ensure_local_naive(now: Optional[datetime] = None) -> datetime:
    """Return a naive datetime in APP_TIMEZONE wall clock (never UTC)."""
    if now is None:
        return local_now()
    if now.tzinfo is not None:
        return now.astimezone(get_app_tz()).replace(tzinfo=None)
    # Naive values from callers are treated as already-local wall clock.
    return now


def _slot_sort_key(slot):
    try:
        return (time_to_minutes(slot.start_time), slot.id or 0)
    except ValueError:
        return (10**9, slot.id or 0)


def _unique_slots(slots):
    seen = set()
    unique = []
    for slot in sorted(slots, key=_slot_sort_key):
        try:
            start_key = minutes_to_hhmm(time_to_minutes(slot.start_time))
            end_key = minutes_to_hhmm(time_to_minutes(slot.end_time))
        except ValueError:
            start_key = str(slot.start_time)
            end_key = str(slot.end_time)
        key = (slot.subject_name.strip().lower(), start_key, end_key, slot.classroom_id)
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
        parse_error = None
    except ValueError as exc:
        start_mins = end_mins = None
        start_norm = str(slot.start_time)
        end_norm = str(slot.end_time)
        parse_error = str(exc)

    return {
        "id": slot.id,
        "day": slot.day_of_week,
        "dayNormalized": normalize_day_name(slot.day_of_week),
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


def resolve_student_classroom_id(
    student,
    *,
    preferred_classroom_id: Optional[int] = None,
    teacher_user=None,
) -> Optional[int]:
    """
    Resolve the classroom/grade whose timetable should be used for a scan.

    Priority:
      1. Classroom whose name matches the student's grade (and optional section)
         within the teacher's classrooms (or the institution).
      2. Classroom linked on the student's personal timetable rows.
      3. Preferred/scanner classroomId when provided.
      4. Teacher's first classroom / institution default.
    """
    from app.models import Classroom

    if student is None:
        return int(preferred_classroom_id) if preferred_classroom_id is not None else None

    institution_id = getattr(student, "institution_id", None)
    grade = str(getattr(student, "grade", None) or "").strip()
    section = str(getattr(student, "section", None) or "").strip()
    preferred = int(preferred_classroom_id) if preferred_classroom_id is not None else None

    query = Classroom.query
    if institution_id is not None:
        query = query.filter_by(institution_id=institution_id)
    if teacher_user is not None and getattr(teacher_user, "role", None) == "teacher":
        query = query.filter_by(teacher_id=teacher_user.id)

    classrooms = query.order_by(Classroom.name.asc(), Classroom.id.asc()).all()

    def _name_matches_grade(classroom) -> bool:
        name = str(getattr(classroom, "name", None) or "").strip().lower()
        if not name or not grade:
            return False
        grade_key = grade.lower()
        section_key = section.lower()
        if name == grade_key:
            return True
        if section_key and name == f"{grade_key} {section_key}".strip():
            return True
        if section_key and name == f"{grade_key}-{section_key}".strip():
            return True
        # Classroom names like "Grade 10 - A" / "10A" / "Grade 10"
        if grade_key in name:
            if not section_key or section_key in name:
                return True
        return False

    if grade and classrooms:
        for classroom in classrooms:
            if _name_matches_grade(classroom):
                print(
                    f"[TIMETABLE] Resolved classroom by grade "
                    f"studentId={getattr(student, 'id', None)} grade={grade!r} "
                    f"section={section!r} -> classroomId={classroom.id} name={classroom.name!r}"
                )
                return int(classroom.id)

    # Student-specific timetable rows that already point at a classroom.
    student_id = getattr(student, "id", None)
    if student_id is not None:
        slot = (
            Timetable.query.filter(
                Timetable.student_id == int(student_id),
                Timetable.classroom_id.isnot(None),
            )
            .order_by(Timetable.id.desc())
            .first()
        )
        if slot and slot.classroom_id:
            # Prefer that classroom if the teacher is allowed to see it.
            if not classrooms or any(c.id == slot.classroom_id for c in classrooms):
                print(
                    f"[TIMETABLE] Resolved classroom from student timetable "
                    f"studentId={student_id} -> classroomId={slot.classroom_id}"
                )
                return int(slot.classroom_id)

    if preferred is not None:
        if not classrooms or any(c.id == preferred for c in classrooms):
            print(
                f"[TIMETABLE] Using preferred/scanner classroomId={preferred} "
                f"studentId={student_id}"
            )
            return preferred

    if classrooms:
        print(
            f"[TIMETABLE] Falling back to first available classroomId={classrooms[0].id} "
            f"studentId={student_id}"
        )
        return int(classrooms[0].id)

    return preferred


def fetch_student_day_slots(
    student_id: int,
    *,
    classroom_id: Optional[int] = None,
    day_of_week: Optional[str] = None,
):
    """
    Fetch today's timetable slots for a student.

    - Day match is case-insensitive (Sunday == sunday).
    - When classroom_id is provided, classroomId must match (or be null on
      student-specific rows).
    - Prefer student-specific rows; fall back to full classroom schedule.
    """
    day = normalize_day_name(day_of_week) or normalize_day_name(current_day_of_week()) or current_day_of_week()
    day_key = day.lower()
    cid = int(classroom_id) if classroom_id is not None else None

    print(
        f"[TIMETABLE] fetch_student_day_slots "
        f"studentId={student_id} classroomId={cid} dayFilter={day!r} (case-insensitive)"
    )

    # 1) Student-specific timetable for today.
    student_query = Timetable.query.filter(
        func.lower(Timetable.day_of_week) == day_key,
        Timetable.student_id == int(student_id),
    )
    if cid is not None:
        # Allow personal rows with matching classroom OR unset classroom.
        student_query = student_query.filter(
            or_(Timetable.classroom_id == cid, Timetable.classroom_id.is_(None))
        )

    student_slots = student_query.order_by(Timetable.id.asc()).all()
    student_slots = _unique_slots(student_slots)
    if student_slots:
        print(
            f"[TIMETABLE] Using student-specific slots count={len(student_slots)} "
            f"studentId={student_id} classroomId={cid} day={day!r}"
        )
        return student_slots

    # 2) Fall back to classroom-wide schedule for today (exact classroom/grade).
    if cid is not None:
        classroom_slots = (
            Timetable.query.filter(
                func.lower(Timetable.day_of_week) == day_key,
                Timetable.classroom_id == cid,
            )
            .order_by(Timetable.id.asc())
            .all()
        )
        classroom_slots = _unique_slots(classroom_slots)
        print(
            f"[TIMETABLE] Falling back to classroom slots count={len(classroom_slots)} "
            f"classroomId={cid} day={day!r}"
        )
        return classroom_slots

    print(
        f"[TIMETABLE] No slots found studentId={student_id} "
        f"classroomId={cid} day={day!r}"
    )
    return []


def filter_slots_by_enrollment(slots, enrolled_subjects: Optional[list]):
    """Keep only timetable slots whose subject is in enrolledSubjects (case-insensitive)."""
    enrolled = [str(name).strip() for name in (enrolled_subjects or []) if str(name).strip()]
    enrolled_keys = {name.lower() for name in enrolled}
    if not enrolled_keys:
        return [], enrolled, enrolled_keys

    matched = [
        slot
        for slot in slots
        if str(getattr(slot, "subject_name", "") or "").strip().lower() in enrolled_keys
    ]
    return matched, enrolled, enrolled_keys


def find_current_class(slots, now_minutes: Optional[int] = None):
    """
    Pick the class in progress using minutes-from-midnight comparison,
    or the next class starting within UPCOMING_WINDOW_MINUTES.
    """
    now_minutes = current_minutes() if now_minutes is None else int(now_minutes)
    in_progress = []
    upcoming = []

    print(
        f"[TIMETABLE] Comparing slots against nowMinutes={now_minutes} "
        f"({minutes_to_hhmm(now_minutes)})"
    )

    for slot in slots:
        try:
            start = time_to_minutes(slot.start_time)
            end = time_to_minutes(slot.end_time)
        except ValueError as exc:
            print(
                f"[TIMETABLE] Skipping slot id={getattr(slot, 'id', None)} "
                f"bad time parse start={slot.start_time!r} end={slot.end_time!r}: {exc}"
            )
            continue

        day_ok = normalize_day_name(slot.day_of_week)
        print(
            f"[TIMETABLE]   compare subject={slot.subject_name!r} "
            f"day={slot.day_of_week!r}->{day_ok!r} "
            f"start={slot.start_time!r}({start}) end={slot.end_time!r}({end}) "
            f"classroomId={slot.classroom_id} :: "
            f"inProgress={start <= now_minutes <= end} "
            f"upcomingIn={start - now_minutes if start >= now_minutes else None}"
        )

        if start <= now_minutes <= end:
            in_progress.append(slot)
        elif 0 <= start - now_minutes <= UPCOMING_WINDOW_MINUTES:
            upcoming.append(slot)

    if in_progress:
        chosen = max(in_progress, key=_slot_sort_key)
        print(
            f"[TIMETABLE] Active class selected subject={chosen.subject_name!r} "
            f"{chosen.start_time}-{chosen.end_time}"
        )
        return chosen
    if upcoming:
        chosen = min(upcoming, key=_slot_sort_key)
        print(
            f"[TIMETABLE] Upcoming class selected subject={chosen.subject_name!r} "
            f"{chosen.start_time}-{chosen.end_time}"
        )
        return chosen

    print("[TIMETABLE] No in-progress or upcoming class matched")
    return None


def collect_continuous_classes(slots, current_slot):
    """
    Return the continuous block containing current_slot.

    Classes are continuous when the gap between one end and the next start
    is <= CONTINUOUS_GAP_MINUTES (including overlapping / back-to-back).
    Walks both forward and backward so scanning during Class B still offers Class A.
    """
    if current_slot is None:
        return []

    ordered = sorted(slots, key=_slot_sort_key)
    try:
        index = next(i for i, slot in enumerate(ordered) if slot.id == current_slot.id)
    except StopIteration:
        return [current_slot]

    selected = [ordered[index]]

    # Backward: earlier continuous classes in the same block.
    cursor = index
    while cursor > 0:
        prev = ordered[cursor - 1]
        current = ordered[cursor]
        try:
            gap = time_to_minutes(current.start_time) - time_to_minutes(prev.end_time)
        except ValueError:
            break
        if gap < 0 or gap <= CONTINUOUS_GAP_MINUTES:
            print(
                f"[TIMETABLE] Continuous class linked (backward) "
                f"{prev.subject_name!r} -> {current.subject_name!r} gap={gap}m"
            )
            selected.insert(0, prev)
            cursor -= 1
            continue
        break

    # Forward: later continuous classes in the same block.
    cursor = index
    while cursor + 1 < len(ordered):
        current = ordered[cursor]
        nxt = ordered[cursor + 1]
        try:
            gap = time_to_minutes(nxt.start_time) - time_to_minutes(current.end_time)
        except ValueError:
            break
        if gap < 0 or gap <= CONTINUOUS_GAP_MINUTES:
            print(
                f"[TIMETABLE] Continuous class linked "
                f"{current.subject_name!r} -> {nxt.subject_name!r} gap={gap}m"
            )
            selected.append(nxt)
            cursor += 1
            continue
        break

    return selected


def collect_gap_scheduled_classes(slots, continuous_slots, now_minutes: Optional[int] = None):
    """
    Later enrolled classes separated by > CONTINUOUS_GAP_MINUTES from the
    continuous/active block. Shown as "Today's Scheduled Subject" without checkboxes.
    """
    now_minutes = current_minutes() if now_minutes is None else int(now_minutes)
    continuous_ids = {slot.id for slot in (continuous_slots or [])}
    ordered = sorted(slots, key=_slot_sort_key)

    last_continuous_end = None
    for slot in continuous_slots or []:
        try:
            end = time_to_minutes(slot.end_time)
        except ValueError:
            continue
        if last_continuous_end is None or end > last_continuous_end:
            last_continuous_end = end

    scheduled = []
    for slot in ordered:
        if slot.id in continuous_ids:
            continue
        try:
            start = time_to_minutes(slot.start_time)
            end = time_to_minutes(slot.end_time)
        except ValueError:
            continue

        # Only future / remaining classes (not already finished).
        if end < now_minutes:
            continue

        if last_continuous_end is not None:
            gap = start - last_continuous_end
            if gap <= CONTINUOUS_GAP_MINUTES:
                # Should have been part of continuous block; skip defensively.
                continue
            print(
                f"[TIMETABLE] Gap/interval class (no checkbox) "
                f"subject={slot.subject_name!r} gapAfterContinuous={gap}m"
            )
            scheduled.append(slot)
            continue

        # No active continuous block — still surface upcoming enrolled classes as info-only.
        if start > now_minutes:
            print(
                f"[TIMETABLE] Upcoming gap/interval class (no checkbox) "
                f"subject={slot.subject_name!r} startsIn={start - now_minutes}m"
            )
            scheduled.append(slot)

    return scheduled


def _slot_payload(slot, *, is_current=False, continuous=False, selectable=True, default_checked=True):
    try:
        start_mins = time_to_minutes(slot.start_time)
        end_mins = time_to_minutes(slot.end_time)
        start_norm = minutes_to_hhmm(start_mins)
        end_norm = minutes_to_hhmm(end_mins)
    except ValueError:
        start_norm = str(slot.start_time)
        end_norm = str(slot.end_time)

    return {
        "id": slot.id,
        "subjectId": slot.id,
        "subject_id": slot.id,
        "subjectName": slot.subject_name,
        "subject_name": slot.subject_name,
        "startTime": slot.start_time,
        "start_time": slot.start_time,
        "endTime": slot.end_time,
        "end_time": slot.end_time,
        "startNormalized": start_norm,
        "endNormalized": end_norm,
        "timeRange": f"{start_norm} - {end_norm}",
        "time_range": f"{start_norm} - {end_norm}",
        "isCurrent": bool(is_current),
        "is_current": bool(is_current),
        "continuous": bool(continuous),
        "selectable": bool(selectable),
        "canMark": bool(selectable),
        "can_mark": bool(selectable),
        "defaultChecked": bool(default_checked) if selectable else False,
        "default_checked": bool(default_checked) if selectable else False,
        "label": (
            "Today's Scheduled Subject"
            if not selectable
            else ("Continuous" if continuous and not is_current else "Current")
        ),
    }


def resolve_auto_mark_subjects(
    student_id: int,
    *,
    classroom_id: Optional[int] = None,
    enrolled_subjects: Optional[list] = None,
    now: Optional[datetime] = None,
):
    """
    Resolve which subjects may be marked Present for this scan.

    Dual validation (both required):
    1. Local timezone day + startTime/endTime window (APP_TIMEZONE).
    2. Subject must also appear in the student's enrolledSubjects list.
    3. Timetable rows must match the student's classroom/grade when provided.

    Continuous classes (gap <= 15 min): returned in selectableSubjects with checkboxes.
    Interval/gap classes (gap > 15 min): returned in scheduledSubjects without checkboxes.
    """
    now = ensure_local_naive(now)
    day_canonical = normalize_day_name(current_day_of_week(now)) or current_day_of_week(now)
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

    # Extra safety: drop rows whose day does not normalize to today, or classroom mismatch.
    filtered = []
    for slot in slots:
        slot_day = normalize_day_name(slot.day_of_week)
        if slot_day is None or slot_day.lower() != day_canonical.lower():
            print(
                f"[TIMETABLE] Dropping slot id={slot.id} day mismatch "
                f"slotDay={slot.day_of_week!r} currentDay={day_canonical!r}"
            )
            continue
        if classroom_id is not None and slot.classroom_id is not None:
            if int(slot.classroom_id) != int(classroom_id):
                print(
                    f"[TIMETABLE] Dropping slot id={slot.id} classroom mismatch "
                    f"slotClassroomId={slot.classroom_id} scanClassroomId={classroom_id}"
                )
                continue
        filtered.append(slot)
    slots = filtered

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

    # Dual validation step 1: enrolledSubjects must be present and match slot subjects.
    enrolled_slots, enrolled, enrolled_keys = filter_slots_by_enrollment(slots, enrolled_subjects)
    print(f"[TIMETABLE] enrolledSubjects={enrolled}")
    print(
        f"[TIMETABLE] enrollmentFilter "
        f"before={len(slots)} after={len(enrolled_slots)} "
        f"subjects={[slot.subject_name for slot in enrolled_slots]}"
    )

    empty_plan = {
        "dayOfWeek": day_canonical,
        "currentTime": current_time,
        "currentMinutes": now_minutes,
        "timezone": APP_TIMEZONE,
        "slots": enrolled_slots,
        "eligibleSlots": [],
        "selectableSubjects": [],
        "scheduledSubjects": [],
        "continuousGroup": False,
        "subjects": [],
        "currentSlot": None,
        "enrolledSubjects": enrolled,
        "classroomId": classroom_id,
        "reason": None,
    }

    if not enrolled_keys:
        print("[TIMETABLE] No enrolledSubjects — dual validation failed")
        empty_plan["reason"] = "not_enrolled"
        print("=" * 60)
        return empty_plan

    if not slots:
        print("[TIMETABLE] No timetable rows for today/classroom — nothing to mark")
        empty_plan["reason"] = "no_timetable"
        print("=" * 60)
        return empty_plan

    if not enrolled_slots:
        print(
            "[TIMETABLE] Timetable exists but none of today's subjects are in enrolledSubjects"
        )
        empty_plan["reason"] = "not_enrolled_for_active"
        print("=" * 60)
        return empty_plan

    # Dual validation step 2: active/upcoming window among enrolled slots only.
    current = find_current_class(enrolled_slots, now_minutes=now_minutes)

    if current is None:
        # No markable window — still return gap/upcoming classes as info-only.
        scheduled_slots = collect_gap_scheduled_classes(
            enrolled_slots, continuous_slots=[], now_minutes=now_minutes
        )
        scheduled = [
            _slot_payload(slot, is_current=False, continuous=False, selectable=False)
            for slot in scheduled_slots
        ]
        print(
            f"[TIMETABLE] No active/upcoming ENROLLED slot at {current_time}; "
            f"scheduledInfoOnly={len(scheduled)}"
        )
        empty_plan["scheduledSubjects"] = scheduled
        empty_plan["reason"] = "no_active_slot"
        print("=" * 60)
        return empty_plan

    print(
        f"[TIMETABLE] Selected current enrolled slot subject={current.subject_name!r} "
        f"{current.start_time}-{current.end_time}"
    )

    # Continuous block (<= 15 min gaps) → checkboxes / eligible to mark.
    eligible = collect_continuous_classes(enrolled_slots, current)
    subjects = [slot.subject_name for slot in eligible]
    print(f"[TIMETABLE] continuousBlock subjectsToMark={subjects}")

    # Later classes with > 15 min gap → display only, no checkbox.
    scheduled_slots = collect_gap_scheduled_classes(
        enrolled_slots, continuous_slots=eligible, now_minutes=now_minutes
    )
    print(
        f"[TIMETABLE] gap/interval scheduledSubjects="
        f"{[slot.subject_name for slot in scheduled_slots]}"
    )
    print("=" * 60)

    selectable = []
    for index, slot in enumerate(eligible):
        is_current = bool(current and slot.id == current.id)
        selectable.append(
            _slot_payload(
                slot,
                is_current=is_current,
                continuous=index > 0 or (len(eligible) > 1 and not is_current),
                selectable=True,
                default_checked=True,
            )
        )

    scheduled = [
        _slot_payload(slot, is_current=False, continuous=False, selectable=False)
        for slot in scheduled_slots
    ]

    return {
        "dayOfWeek": day_canonical,
        "currentTime": current_time,
        "currentMinutes": now_minutes,
        "timezone": APP_TIMEZONE,
        "slots": enrolled_slots,
        "eligibleSlots": eligible,
        "selectableSubjects": selectable,
        "scheduledSubjects": scheduled,
        "continuousGroup": len(selectable) > 1,
        "subjects": subjects,
        "currentSlot": current,
        "enrolledSubjects": enrolled,
        "classroomId": classroom_id,
        "reason": None,
    }
