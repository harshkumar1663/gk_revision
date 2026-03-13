from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

REVISION_RATIOS = {
    "R1": 0.03,
    "R2": 0.08,
    "R3": 0.16,
    "R4": 0.30,
    "R5": 0.50,
    "R6": 0.75,
    "R7": 0.90,
}

STAGE_WEIGHTS = {
    "R1": 3.0,
    "R2": 2.5,
    "R3": 2.0,
    "R4": 1.5,
    "R5": 1.0,
    "R6": 1.0,
    "R7": 1.0,
}

STAGE_ORDER = ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]
STAGE_ORDER_INDEX = {stage: idx for idx, stage in enumerate(STAGE_ORDER)}

MAX_DAILY_LOAD = 10.0
SOFT_LIMIT = 8.0
MAX_SAME_CATEGORY_PER_DAY = 3

OFFSETS = [0, 1, -1, 2, -2, 3]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _to_date_str(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _difficulty_weight(difficulty: int) -> float:
    return 0.8 + (difficulty * 0.1)


def calculate_revision_weight(stage: str, difficulty: int) -> float:
    stage_weight = STAGE_WEIGHTS.get(stage, 1.0)
    return round(stage_weight * _difficulty_weight(difficulty), 2)


def _get_capacity(capacity: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    capacity = capacity or {}
    return {
        "max_daily_load": float(capacity.get("max_daily_load", MAX_DAILY_LOAD)),
        "soft_limit": float(capacity.get("soft_limit", SOFT_LIMIT)),
        "max_same_category_per_day": int(capacity.get("max_same_category_per_day", MAX_SAME_CATEGORY_PER_DAY)),
    }


def calculate_daily_load(
    data: Dict[str, Any],
    person: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Dict[str, Any]]:
    """Aggregate daily cognitive load with breakdown details for timeline and scheduling."""
    load_map: Dict[str, Dict[str, Any]] = {}

    for lecture_id, lecture in data.get("lectures", {}).items():
        difficulty = int(lecture.get("difficulty", 3))
        category = lecture.get("category", "Miscellaneous")
        lecture_name = lecture.get("name", lecture_id)

        for stage, date_str in lecture.get("revision_dates", {}).items():
            revision_date = _parse_date(date_str)
            if start_date and revision_date < start_date:
                continue
            if end_date and revision_date > end_date:
                continue

            weight = calculate_revision_weight(stage, difficulty)
            day_bucket = load_map.setdefault(
                date_str,
                {
                    "total_load": 0.0,
                    "revision_count": 0,
                    "stage_breakdown": defaultdict(int),
                    "category_breakdown": defaultdict(int),
                    "revisions": [],
                },
            )

            grade = None
            if person:
                grade = data.get("persons", {}).get(person, {}).get("grades", {}).get(f"{lecture_id}_{stage}")

            day_bucket["total_load"] += weight
            day_bucket["revision_count"] += 1
            day_bucket["stage_breakdown"][stage] += 1
            day_bucket["category_breakdown"][category] += 1
            day_bucket["revisions"].append(
                {
                    "lecture_id": lecture_id,
                    "lecture_name": lecture_name,
                    "stage": stage,
                    "difficulty": difficulty,
                    "category": category,
                    "weight": weight,
                    "date": date_str,
                    "grade": grade,
                }
            )

    for key, bucket in load_map.items():
        bucket["total_load"] = round(bucket["total_load"], 2)
        bucket["stage_breakdown"] = dict(sorted(bucket["stage_breakdown"].items(), key=lambda x: STAGE_ORDER_INDEX.get(x[0], 99)))
        bucket["category_breakdown"] = dict(sorted(bucket["category_breakdown"].items(), key=lambda x: x[0]))
        bucket["revisions"].sort(key=lambda x: (STAGE_ORDER_INDEX.get(x["stage"], 99), x["lecture_name"]))

    return load_map


def _build_stage_boundaries(existing_dates: Dict[str, str], stage: str) -> Tuple[Optional[date], Optional[date]]:
    idx = STAGE_ORDER_INDEX[stage]
    prev_date = None
    next_date = None

    for prev_idx in range(idx - 1, -1, -1):
        prev_stage = STAGE_ORDER[prev_idx]
        prev_val = existing_dates.get(prev_stage)
        if prev_val:
            prev_date = _parse_date(prev_val)
            break

    for next_idx in range(idx + 1, len(STAGE_ORDER)):
        next_stage = STAGE_ORDER[next_idx]
        next_val = existing_dates.get(next_stage)
        if next_val:
            next_date = _parse_date(next_val)
            break

    return prev_date, next_date


def _is_valid_candidate(
    candidate: date,
    stage: str,
    category: str,
    stage_weight: float,
    study_date: date,
    exam_date: date,
    existing_dates: Dict[str, str],
    day_loads: Dict[str, float],
    day_category_counts: Dict[str, Dict[str, int]],
    capacity: Dict[str, float],
) -> bool:
    if candidate < study_date or candidate > exam_date:
        return False

    prev_date, next_date = _build_stage_boundaries(existing_dates, stage)
    if prev_date and candidate < prev_date:
        return False
    if next_date and candidate > next_date:
        return False

    day_key = _to_date_str(candidate)
    if (day_loads.get(day_key, 0.0) + stage_weight) > capacity["max_daily_load"]:
        return False

    category_count = day_category_counts.get(day_key, {}).get(category, 0)
    if category_count >= int(capacity["max_same_category_per_day"]):
        return False

    return True


def find_balanced_date(
    ideal_date: date,
    stage: str,
    category: str,
    stage_weight: float,
    study_date: date,
    exam_date: date,
    existing_dates: Dict[str, str],
    day_loads: Dict[str, float],
    day_category_counts: Dict[str, Dict[str, int]],
    capacity: Optional[Dict[str, Any]] = None,
    exam_less_than_45_days: bool = False,
) -> date:
    """Find a balanced date respecting limits, ordering and category constraints."""
    cap = _get_capacity(capacity)
    effective_soft_limit = cap["soft_limit"]

    # Urgent window: avoid shifting early stages and allow stacking up to max load.
    if exam_less_than_45_days and stage in {"R1", "R2", "R3"}:
        if _is_valid_candidate(
            ideal_date,
            stage,
            category,
            stage_weight,
            study_date,
            exam_date,
            existing_dates,
            day_loads,
            day_category_counts,
            {**cap, "soft_limit": cap["max_daily_load"]},
        ):
            return ideal_date

    ideal_key = _to_date_str(ideal_date)
    ideal_load_after = day_loads.get(ideal_key, 0.0) + stage_weight

    # If within soft limit, keep ideal date if it satisfies hard constraints.
    if ideal_load_after <= effective_soft_limit and _is_valid_candidate(
        ideal_date,
        stage,
        category,
        stage_weight,
        study_date,
        exam_date,
        existing_dates,
        day_loads,
        day_category_counts,
        cap,
    ):
        return ideal_date

    for offset in OFFSETS:
        candidate = ideal_date + timedelta(days=offset)
        if _is_valid_candidate(
            candidate,
            stage,
            category,
            stage_weight,
            study_date,
            exam_date,
            existing_dates,
            day_loads,
            day_category_counts,
            cap,
        ):
            # In urgent window, we allow any candidate under max; outside, prefer <= soft.
            cand_key = _to_date_str(candidate)
            candidate_load_after = day_loads.get(cand_key, 0.0) + stage_weight
            if exam_less_than_45_days or candidate_load_after <= effective_soft_limit:
                return candidate

    # Fallback: broaden search while preserving hard constraints.
    search_start = max(study_date, ideal_date - timedelta(days=7))
    search_end = min(exam_date, ideal_date + timedelta(days=14))
    best_candidate = ideal_date
    best_score = float("inf")

    cursor = search_start
    while cursor <= search_end:
        if _is_valid_candidate(
            cursor,
            stage,
            category,
            stage_weight,
            study_date,
            exam_date,
            existing_dates,
            day_loads,
            day_category_counts,
            cap,
        ):
            key = _to_date_str(cursor)
            projected_load = day_loads.get(key, 0.0) + stage_weight
            overload_penalty = max(0.0, projected_load - effective_soft_limit)
            score = (abs((cursor - ideal_date).days) * 10.0) + overload_penalty
            if score < best_score:
                best_score = score
                best_candidate = cursor
        cursor += timedelta(days=1)

    return best_candidate


def _build_existing_load_context(
    data: Dict[str, Any],
    exclude_lecture_id: Optional[str] = None,
) -> Tuple[Dict[str, float], Dict[str, Dict[str, int]]]:
    day_loads: Dict[str, float] = defaultdict(float)
    day_category_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for lecture_id, lecture in data.get("lectures", {}).items():
        if exclude_lecture_id and lecture_id == exclude_lecture_id:
            continue

        difficulty = int(lecture.get("difficulty", 3))
        category = lecture.get("category", "Miscellaneous")
        for stage, date_str in lecture.get("revision_dates", {}).items():
            day_loads[date_str] += calculate_revision_weight(stage, difficulty)
            day_category_counts[date_str][category] += 1

    rounded_loads = {k: round(v, 2) for k, v in day_loads.items()}
    categories = {d: dict(v) for d, v in day_category_counts.items()}
    return rounded_loads, categories


def calculate_revision_dates_balanced(
    study_date_str: str,
    exam_date_str: str,
    difficulty: int,
    category: str,
    data: Dict[str, Any],
    lecture_id: Optional[str] = None,
    capacity: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Dict[str, str]:
    """Generate load-balanced R1-R7 schedule while preserving stage order and hard constraints."""
    if not exam_date_str:
        return {}

    study_date = _parse_date(study_date_str)
    exam_date = _parse_date(exam_date_str)
    today = today or date.today()

    total_days = (exam_date - study_date).days
    if total_days <= 0:
        return {}

    day_loads, day_category_counts = _build_existing_load_context(data, exclude_lecture_id=lecture_id)

    cap = _get_capacity(capacity)
    exam_less_than_45_days = (exam_date - today).days < 45

    difficulty_factor = 1.0 + (3 - int(difficulty)) * 0.15
    revision_dates: Dict[str, str] = {}

    for stage in STAGE_ORDER:
        ratio = REVISION_RATIOS[stage]
        ideal_offset = int(total_days * ratio * difficulty_factor)
        ideal_date = study_date + timedelta(days=ideal_offset)
        if ideal_date > exam_date:
            break

        stage_weight = calculate_revision_weight(stage, int(difficulty))
        chosen = find_balanced_date(
            ideal_date=ideal_date,
            stage=stage,
            category=category,
            stage_weight=stage_weight,
            study_date=study_date,
            exam_date=exam_date,
            existing_dates=revision_dates,
            day_loads=day_loads,
            day_category_counts=day_category_counts,
            capacity=cap,
            exam_less_than_45_days=exam_less_than_45_days,
        )

        chosen_key = _to_date_str(chosen)
        revision_dates[stage] = chosen_key
        day_loads[chosen_key] = round(day_loads.get(chosen_key, 0.0) + stage_weight, 2)
        if chosen_key not in day_category_counts:
            day_category_counts[chosen_key] = {}
        day_category_counts[chosen_key][category] = day_category_counts[chosen_key].get(category, 0) + 1

    return revision_dates


def auto_rebalance_window(
    data: Dict[str, Any],
    person: str,
    start_date: date,
    days: int = 7,
    capacity: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Shift low-priority revisions in an upcoming window to smooth overloaded days."""
    result_data = deepcopy(data)
    cap = _get_capacity(capacity)

    exam_date_str = result_data.get("exam_date")
    if not exam_date_str:
        return result_data, {"moved": 0, "overload_days_before": 0, "overload_days_after": 0, "changes": []}

    exam_date = _parse_date(exam_date_str)
    end_date = start_date + timedelta(days=max(days - 1, 0))
    graded = result_data.get("persons", {}).get(person, {}).get("grades", {})

    load_map = calculate_daily_load(result_data, person=person)

    def day_load(day: date) -> float:
        return load_map.get(_to_date_str(day), {}).get("total_load", 0.0)

    overloaded_days = []
    cursor = start_date
    while cursor <= end_date:
        if day_load(cursor) > cap["max_daily_load"]:
            overloaded_days.append(cursor)
        cursor += timedelta(days=1)

    overload_before = len(overloaded_days)
    changes: List[Dict[str, Any]] = []

    priority = {"R7": 1, "R6": 2, "R5": 3, "R4": 4, "R3": 5, "R2": 6, "R1": 7}
    in_final_45 = (exam_date - date.today()).days < 45

    for overloaded_day in overloaded_days:
        day_key = _to_date_str(overloaded_day)
        revisions = load_map.get(day_key, {}).get("revisions", [])
        # Low-priority first and heavier first for maximum impact.
        candidates = sorted(
            revisions,
            key=lambda r: (priority.get(r["stage"], 99), -r["weight"]),
        )

        for rev in candidates:
            lecture_id = rev["lecture_id"]
            stage = rev["stage"]
            grade_key = f"{lecture_id}_{stage}"
            if graded.get(grade_key):
                continue
            if in_final_45 and stage in {"R1", "R2", "R3"}:
                continue

            lecture = result_data.get("lectures", {}).get(lecture_id)
            if not lecture:
                continue

            current_dates = lecture.get("revision_dates", {})
            if stage not in current_dates:
                continue

            current_date = _parse_date(current_dates[stage])
            if current_date != overloaded_day:
                continue

            difficulty = int(lecture.get("difficulty", 3))
            category = lecture.get("category", "Miscellaneous")
            weight = calculate_revision_weight(stage, difficulty)

            prev_date, next_date = _build_stage_boundaries(current_dates, stage)
            search_from = max(current_date + timedelta(days=1), prev_date or current_date)
            search_to = min(exam_date, next_date or exam_date)

            moved_to = None
            target = search_from
            while target <= search_to:
                target_key = _to_date_str(target)
                target_bucket = load_map.get(target_key, {})
                target_load = target_bucket.get("total_load", 0.0)
                target_category_count = target_bucket.get("category_breakdown", {}).get(category, 0)

                if target_load + weight <= cap["max_daily_load"] and target_category_count < int(cap["max_same_category_per_day"]):
                    moved_to = target
                    break
                target += timedelta(days=1)

            if not moved_to:
                continue

            moved_key = _to_date_str(moved_to)
            current_dates[stage] = moved_key

            # Recompute load map after each successful move to keep constraints consistent.
            load_map = calculate_daily_load(result_data, person=person)
            changes.append(
                {
                    "lecture_id": lecture_id,
                    "lecture_name": lecture.get("name", lecture_id),
                    "stage": stage,
                    "from": day_key,
                    "to": moved_key,
                    "weight": weight,
                }
            )

            if day_load(overloaded_day) <= cap["max_daily_load"]:
                break

    overload_after = 0
    cursor = start_date
    while cursor <= end_date:
        if day_load(cursor) > cap["max_daily_load"]:
            overload_after += 1
        cursor += timedelta(days=1)

    return result_data, {
        "moved": len(changes),
        "overload_days_before": overload_before,
        "overload_days_after": overload_after,
        "changes": changes,
    }
