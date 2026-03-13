from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import pstdev
from typing import Any, Dict, List

from scheduling_engine import (
    SOFT_LIMIT,
    STAGE_ORDER_INDEX,
    calculate_daily_load,
)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _safe_pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _build_graded_records(data: Dict[str, Any], person: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    grades = data.get("persons", {}).get(person, {}).get("grades", {})

    for lecture_id, lecture in data.get("lectures", {}).items():
        for stage, date_str in lecture.get("revision_dates", {}).items():
            grade_key = f"{lecture_id}_{stage}"
            grade = grades.get(grade_key)
            if not grade:
                continue

            records.append(
                {
                    "lecture_id": lecture_id,
                    "lecture_name": lecture.get("name", lecture_id),
                    "date": date_str,
                    "stage": stage,
                    "category": lecture.get("category", "Miscellaneous"),
                    "difficulty": int(lecture.get("difficulty", 3)),
                    "grade": grade,
                }
            )

    records.sort(key=lambda r: (r["date"], STAGE_ORDER_INDEX.get(r["stage"], 99)))
    return records


def analyze_performance_patterns(data: Dict[str, Any], person: str) -> Dict[str, Any]:
    """Compute load-performance relationships and trends for the selected person."""
    records = _build_graded_records(data, person)
    load_map = calculate_daily_load(data, person=person)

    fail_loads: List[float] = []
    perfect_loads: List[float] = []
    over_soft_total = 0
    over_soft_fail = 0

    category_total = defaultdict(int)
    category_fail = defaultdict(int)

    stage_total = defaultdict(int)
    stage_fail = defaultdict(int)

    daily_grade_rollup = defaultdict(lambda: {"total": 0, "fail": 0, "perfect": 0, "partial": 0, "skip": 0})

    for rec in records:
        day_load = load_map.get(rec["date"], {}).get("total_load", 0.0)
        grade = rec["grade"]

        if grade == "FAIL":
            fail_loads.append(day_load)
            category_fail[rec["category"]] += 1
            stage_fail[rec["stage"]] += 1
        if grade == "PERFECT":
            perfect_loads.append(day_load)

        if day_load > SOFT_LIMIT:
            over_soft_total += 1
            if grade == "FAIL":
                over_soft_fail += 1

        category_total[rec["category"]] += 1
        stage_total[rec["stage"]] += 1

        bucket = daily_grade_rollup[rec["date"]]
        bucket["total"] += 1
        if grade == "FAIL":
            bucket["fail"] += 1
        elif grade == "PERFECT":
            bucket["perfect"] += 1
        elif grade == "PARTIAL":
            bucket["partial"] += 1
        elif grade == "SKIP":
            bucket["skip"] += 1

    # Weekly trend (last 8 weeks)
    weekly = defaultdict(lambda: {"total": 0, "fail": 0, "perfect": 0})
    for rec in records:
        day = _parse_date(rec["date"])
        iso_year, iso_week, _ = day.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        weekly[key]["total"] += 1
        if rec["grade"] == "FAIL":
            weekly[key]["fail"] += 1
        if rec["grade"] == "PERFECT":
            weekly[key]["perfect"] += 1

    weekly_keys = sorted(weekly.keys())[-8:]
    weekly_trend = []
    for week_key in weekly_keys:
        totals = weekly[week_key]
        weekly_trend.append(
            {
                "week": week_key,
                "total": totals["total"],
                "fail_rate": _safe_pct(totals["fail"], totals["total"]),
                "perfect_rate": _safe_pct(totals["perfect"], totals["total"]),
            }
        )

    category_fail_rate = {
        cat: _safe_pct(category_fail.get(cat, 0), total)
        for cat, total in sorted(category_total.items(), key=lambda x: x[0])
    }

    stage_fail_frequency = {
        stage: {
            "fail_count": stage_fail.get(stage, 0),
            "fail_rate": _safe_pct(stage_fail.get(stage, 0), total),
        }
        for stage, total in sorted(stage_total.items(), key=lambda x: STAGE_ORDER_INDEX.get(x[0], 99))
    }

    avg_fail_load = round(sum(fail_loads) / len(fail_loads), 2) if fail_loads else 0.0
    avg_perfect_load = round(sum(perfect_loads) / len(perfect_loads), 2) if perfect_loads else 0.0

    return {
        "average_load_fail_days": avg_fail_load,
        "average_load_perfect_days": avg_perfect_load,
        "fail_rate_over_soft_limit": _safe_pct(over_soft_fail, over_soft_total),
        "weekly_performance_trend": weekly_trend,
        "category_wise_fail_rate": category_fail_rate,
        "stage_wise_fail_frequency": stage_fail_frequency,
        "graded_samples": len(records),
    }


def timeline_advanced_metrics(
    load_series: List[Dict[str, Any]],
    max_daily_load: float,
) -> Dict[str, Any]:
    """Compute dashboard metrics for the cognitive timeline."""
    if not load_series:
        return {
            "avg_30_day_load": 0.0,
            "peak_load_date": None,
            "peak_load_value": 0.0,
            "weekly_volatility": 0.0,
            "recovery_days": 0,
            "overload_days": 0,
        }

    sorted_points = sorted(load_series, key=lambda x: x["date"])
    values = [float(p["load"]) for p in sorted_points]
    dates = [p["date"] for p in sorted_points]

    window_30 = values[:30] if len(values) >= 30 else values
    avg_30 = round(sum(window_30) / len(window_30), 2) if window_30 else 0.0

    peak_idx = max(range(len(values)), key=lambda idx: values[idx])
    peak_date = dates[peak_idx]
    peak_value = round(values[peak_idx], 2)

    rolling_week_avgs = []
    if len(values) >= 7:
        for idx in range(len(values) - 6):
            segment = values[idx : idx + 7]
            rolling_week_avgs.append(sum(segment) / 7.0)
    volatility = round(pstdev(rolling_week_avgs), 3) if len(rolling_week_avgs) >= 2 else 0.0

    recovery_days = sum(1 for v in values if v < 3.0)
    overload_days = sum(1 for v in values if v > max_daily_load)

    return {
        "avg_30_day_load": avg_30,
        "peak_load_date": peak_date,
        "peak_load_value": peak_value,
        "weekly_volatility": volatility,
        "recovery_days": recovery_days,
        "overload_days": overload_days,
    }
