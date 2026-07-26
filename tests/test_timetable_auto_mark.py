"""Unit tests for timetable time/day matching helpers (no DB required)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.timetable_auto_mark import (
    collect_continuous_classes,
    collect_gap_scheduled_classes,
    current_day_of_week,
    current_minutes,
    ensure_local_naive,
    filter_slots_by_enrollment,
    find_current_class,
    format_hhmm,
    minutes_to_hhmm,
    normalize_day_name,
    time_to_minutes,
)


class _FakeSlot:
    def __init__(self, id, subject_name, start_time, end_time, day_of_week="Sunday", classroom_id=1):
        self.id = id
        self.subject_name = subject_name
        self.start_time = start_time
        self.end_time = end_time
        self.day_of_week = day_of_week
        self.classroom_id = classroom_id
        self.student_id = None


def test_time_to_minutes_24h_and_12h():
    assert time_to_minutes("09:15") == 9 * 60 + 15
    assert time_to_minutes("9:15") == 9 * 60 + 15
    assert time_to_minutes("09:15:00") == 9 * 60 + 15
    assert time_to_minutes("9:15 AM") == 9 * 60 + 15
    assert time_to_minutes("09:15AM") == 9 * 60 + 15
    assert time_to_minutes("1:30 PM") == 13 * 60 + 30
    assert time_to_minutes("12:00 PM") == 12 * 60
    assert time_to_minutes("12:00 AM") == 0


def test_normalize_day_case_insensitive():
    assert normalize_day_name("sunday") == "Sunday"
    assert normalize_day_name("SUNDAY") == "Sunday"
    assert normalize_day_name("Sunday") == "Sunday"


def test_find_current_class_uses_minutes():
    slots = [
        _FakeSlot(1, "Physics", "10:00", "11:00"),
        _FakeSlot(2, "Maths", "11:00", "12:00"),
    ]
    # 10:15 → Physics
    assert find_current_class(slots, now_minutes=10 * 60 + 15).subject_name == "Physics"
    # 11:15 → Maths
    assert find_current_class(slots, now_minutes=11 * 60 + 15).subject_name == "Maths"
    # 09:55 with upcoming window 10 → Physics upcoming
    assert find_current_class(slots, now_minutes=9 * 60 + 55).subject_name == "Physics"


def test_ensure_local_naive_converts_utc():
    utc = datetime(2026, 7, 26, 3, 30, tzinfo=ZoneInfo("UTC"))  # 09:00 IST
    local = ensure_local_naive(utc)
    assert local.tzinfo is None
    assert format_hhmm(local) == "09:00"
    assert current_minutes(local) == 9 * 60
    assert current_day_of_week(local) == "Sunday"


def test_minutes_roundtrip():
    assert minutes_to_hhmm(555) == "09:15"
    assert time_to_minutes(minutes_to_hhmm(810)) == 810


def test_filter_slots_by_enrollment_is_strict():
    slots = [
        _FakeSlot(1, "Physics", "10:00", "11:00"),
        _FakeSlot(2, "Chemistry", "11:00", "12:00"),
        _FakeSlot(3, "Maths", "12:00", "13:00"),
    ]
    matched, enrolled, keys = filter_slots_by_enrollment(slots, ["chemistry", "Physics"])
    assert enrolled == ["chemistry", "Physics"]
    assert keys == {"chemistry", "physics"}
    assert [s.subject_name for s in matched] == ["Physics", "Chemistry"]

    empty, enrolled_empty, keys_empty = filter_slots_by_enrollment(slots, [])
    assert empty == []
    assert enrolled_empty == []
    assert keys_empty == set()


def test_dual_validation_active_slot_must_be_enrolled():
    slots = [
        _FakeSlot(1, "Physics", "10:00", "11:00"),
        _FakeSlot(2, "Chemistry", "11:00", "12:00"),
    ]
    enrolled_slots, _, _ = filter_slots_by_enrollment(slots, ["Chemistry"])
    # At 10:15 Physics is active on the full timetable, but student is only in Chemistry.
    assert find_current_class(slots, now_minutes=10 * 60 + 15).subject_name == "Physics"
    assert find_current_class(enrolled_slots, now_minutes=10 * 60 + 15) is None
    # At 11:15 Chemistry is both active and enrolled.
    assert find_current_class(enrolled_slots, now_minutes=11 * 60 + 15).subject_name == "Chemistry"


def test_collect_continuous_bidirectional():
    slots = [
        _FakeSlot(1, "Physics", "10:00", "11:00"),
        _FakeSlot(2, "Chemistry", "11:05", "12:00"),
        _FakeSlot(3, "Maths", "14:00", "15:00"),  # 2h gap — not continuous
    ]
    # Scanning during Chemistry should still offer Physics (backward continuous).
    current = find_current_class(slots, now_minutes=11 * 60 + 30)
    continuous = collect_continuous_classes(slots, current)
    assert [s.subject_name for s in continuous] == ["Physics", "Chemistry"]


def test_gap_scheduled_classes_have_no_checkbox():
    slots = [
        _FakeSlot(1, "Physics", "10:00", "11:00"),
        _FakeSlot(2, "Chemistry", "11:05", "12:00"),
        _FakeSlot(3, "Maths", "14:00", "15:00"),
    ]
    continuous = collect_continuous_classes(slots, slots[0])
    scheduled = collect_gap_scheduled_classes(slots, continuous, now_minutes=10 * 60 + 30)
    assert [s.subject_name for s in continuous] == ["Physics", "Chemistry"]
    assert [s.subject_name for s in scheduled] == ["Maths"]
