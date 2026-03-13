from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict

from scheduling_engine import MAX_DAILY_LOAD, MAX_SAME_CATEGORY_PER_DAY, SOFT_LIMIT

MIN_DYNAMIC_MAX_LOAD = 7
MAX_DYNAMIC_SOFT_LIMIT = 10


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _safe_pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def ensure_person_capacity_schema(data: Dict[str, Any], person: str) -> Dict[str, Any]:
    person_node = data.setdefault("persons", {}).setdefault(person, {})
    person_node.setdefault("grades", {})
    person_node.setdefault("emergency_revisions", {})

    capacity = person_node.get("capacity")
    if not isinstance(capacity, dict):
        capacity = {}

    capacity.setdefault("max_daily_load", MAX_DAILY_LOAD)
    capacity.setdefault("soft_limit", SOFT_LIMIT)
    capacity.setdefault("max_same_category_per_day", MAX_SAME_CATEGORY_PER_DAY)
    person_node["capacity"] = capacity
    return capacity


def get_person_capacity(data: Dict[str, Any], person: str) -> Dict[str, float]:
    capacity = ensure_person_capacity_schema(data, person)
    return {
        "max_daily_load": float(capacity.get("max_daily_load", MAX_DAILY_LOAD)),
        "soft_limit": float(capacity.get("soft_limit", SOFT_LIMIT)),
        "max_same_category_per_day": int(capacity.get("max_same_category_per_day", MAX_SAME_CATEGORY_PER_DAY)),
    }


def get_effective_capacity(data: Dict[str, Any]) -> Dict[str, float]:
    persons = list(data.get("persons", {}).keys()) or ["Harsh", "Divya"]
    capacities = [get_person_capacity(data, p) for p in persons]

    max_daily = min(c["max_daily_load"] for c in capacities) if capacities else MAX_DAILY_LOAD
    soft_limit = min(c["soft_limit"] for c in capacities) if capacities else SOFT_LIMIT
    max_same_category = min(c["max_same_category_per_day"] for c in capacities) if capacities else MAX_SAME_CATEGORY_PER_DAY

    return {
        "max_daily_load": float(max_daily),
        "soft_limit": float(min(soft_limit, max_daily)),
        "max_same_category_per_day": int(max_same_category),
    }


def update_personal_capacity(data: Dict[str, Any], person: str) -> Dict[str, Any]:
    """Adjust per-person capacity from trailing 14-day outcomes (future schedules only)."""
    capacity = ensure_person_capacity_schema(data, person)

    today = date.today()
    window_start = today - timedelta(days=13)
    grades = data.get("persons", {}).get(person, {}).get("grades", {})

    graded_count = 0
    fail_count = 0
    perfect_count = 0

    for lecture_id, lecture in data.get("lectures", {}).items():
        for stage, date_str in lecture.get("revision_dates", {}).items():
            revision_day = _parse_date(date_str)
            if revision_day < window_start or revision_day > today:
                continue

            grade = grades.get(f"{lecture_id}_{stage}")
            if not grade:
                continue

            graded_count += 1
            if grade == "FAIL":
                fail_count += 1
            if grade == "PERFECT":
                perfect_count += 1

    fail_rate = _safe_pct(fail_count, graded_count)
    perfect_rate = _safe_pct(perfect_count, graded_count)

    old_max = float(capacity.get("max_daily_load", MAX_DAILY_LOAD))
    old_soft = float(capacity.get("soft_limit", SOFT_LIMIT))

    new_max = old_max
    new_soft = old_soft

    if fail_rate > 25.0:
        new_max = max(MIN_DYNAMIC_MAX_LOAD, old_max - 1.0)

    if perfect_rate > 70.0:
        new_soft = min(MAX_DYNAMIC_SOFT_LIMIT, old_soft + 1.0)

    new_soft = min(new_soft, new_max)

    capacity["max_daily_load"] = round(new_max, 2)
    capacity["soft_limit"] = round(new_soft, 2)
    capacity["max_same_category_per_day"] = int(capacity.get("max_same_category_per_day", MAX_SAME_CATEGORY_PER_DAY))
    capacity["last_evaluated_on"] = today.strftime("%Y-%m-%d")
    capacity["last_14_day_stats"] = {
        "graded_count": graded_count,
        "fail_rate": fail_rate,
        "perfect_rate": perfect_rate,
    }

    return {
        "updated": (round(old_max, 2) != capacity["max_daily_load"]) or (round(old_soft, 2) != capacity["soft_limit"]),
        "old": {"max_daily_load": old_max, "soft_limit": old_soft},
        "new": {"max_daily_load": capacity["max_daily_load"], "soft_limit": capacity["soft_limit"]},
        "stats": capacity["last_14_day_stats"],
    }
