import streamlit as st
from datetime import datetime, timedelta
import json
import os
import time
from pathlib import Path
import base64
import requests

# Page config
st.set_page_config(
    page_title="SSC GK Smart Revision Tracker", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Fix sidebar collapse button visibility issue
st.markdown("""
    <style>
        /* Force sidebar controls to always render */
        [data-testid="collapsedControl"] {
            display: flex !important;
            visibility: visible !important;
            opacity: 1 !important;
        }
        
        /* Ensure sidebar button is always visible */
        section[data-testid="stSidebar"] button[kind="header"] {
            display: flex !important;
        }
        
        /* Force sidebar to render properly */
        section[data-testid="stSidebar"] {
            min-height: 100vh;
        }

        /* High-visibility marker for emergency revisions */
        .emergency-chip {
            display: inline-block;
            background: #ff3b30;
            color: #ffffff;
            font-weight: 700;
            font-size: 12px;
            letter-spacing: 0.4px;
            padding: 4px 10px;
            border-radius: 999px;
            margin-bottom: 8px;
        }
    </style>
""", unsafe_allow_html=True)

# Constants
REVISION_RATIOS = {
    "R1": 0.03,
    "R2": 0.08,
    "R3": 0.16,
    "R4": 0.30,
    "R5": 0.50,
    "R6": 0.75,
    "R7": 0.90
}

GRADES = ["FAIL", "PARTIAL", "PERFECT", "SKIP"]
PERSONS = ["Harsh", "Divya"]
CATEGORIES = [
    "Ancient History",
    "Medieval History",
    "Modern History",
    "Geography",
    "Polity",
    "Economy",
    "Science",
    "Current Affairs",
    "Miscellaneous"
]

LEGACY_CATEGORY_ALIASES = {
    "History": "Ancient History"
}

# Use relative path for data file (works both locally and on Streamlit Cloud)
DATA_FILE = Path(__file__).parent.parent / "gk_data.json"

# GitHub storage configuration
GITHUB_OWNER = "harshkumar1663"
GITHUB_REPO = "gk_revision_data"
GITHUB_BRANCH = "main"
GITHUB_FILE_PATH = "gk_data.json"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

# Date formatting helpers
def get_grade_value(grade_entry):
    """Extract grade string from either legacy   string format or new dict format."""
    if isinstance(grade_entry, dict):
        return grade_entry.get("grade", "")
    return grade_entry or ""


def format_date_for_display(date_str):
    """Convert YYYY-MM-DD to DD/MM/YY for display"""
    if not date_str:
        return ""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.strftime("%d/%m/%y")

def format_date_compact(date_str):
    """Convert YYYY-MM-DD to compact format like '1 Jan', '14 Apr' for revision plan"""
    if not date_str:
        return ""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.strftime("%-d %b").replace(" 0", " ")

def format_date_for_storage(date_obj):
    """Convert date object to YYYY-MM-DD for storage"""
    return date_obj.strftime("%Y-%m-%d")

# Initialize session state
if "current_person" not in st.session_state:
    st.session_state.current_person = "Harsh"

if "current_view" not in st.session_state:
    st.session_state.current_view = "Home"


def _default_data():
    return {
        "exam_date": None,
        "lectures": {},
        "persons": {
            "Harsh": {"grades": {}, "emergency_revisions": {}},
            "Divya": {"grades": {}, "emergency_revisions": {}}
        }
    }


def _normalize_category(category):
    return LEGACY_CATEGORY_ALIASES.get(category, category)


def _github_headers():
    # print("[GitHub] Retrieving authentication token...")
    try:
        token = st.secrets.get("GITHUB_TOKEN")
        
    except Exception:
        token = None
    if not token:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("[GitHub] Missing GITHUB_TOKEN in Streamlit secrets.")
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "streamlit-gk-revision-app",
        "Cache-Control": "no-cache"
    }


def _log_github_error(prefix, response):
    try:
        body = response.text
    except Exception:
        body = "<no response body>"
    print(f"[GitHub] {prefix} failed: {response.status_code} {body}")


def load_data():
    """Load data from GitHub JSON file with legacy migration support"""
    headers = _github_headers()
    if not headers:
        return _default_data()

    try:
        response = requests.get(
            GITHUB_API_URL,
            headers=headers,
            params={"ref": GITHUB_BRANCH, "ts": int(time.time())},
            timeout=10
        )
    except requests.RequestException:
        return _default_data()

    if response.status_code == 404:
        return _default_data()

    if not response.ok:
        _log_github_error("GET", response)
        return _default_data()

    payload = response.json()
    st.session_state.last_loaded_sha = payload.get("sha")
    content_b64 = payload.get("content", "")
    if not content_b64:
        return _default_data()

    try:
        decoded = base64.b64decode(content_b64).decode("utf-8")
        data = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return _default_data()

    # Migrate legacy schema if needed
    if "persons" not in data:
        data["persons"] = {
            "Harsh": {"grades": {}, "emergency_revisions": {}},
            "Divya": {"grades": {}, "emergency_revisions": {}}
        }

    for person in PERSONS:
        if person not in data["persons"]:
            data["persons"][person] = {"grades": {}, "emergency_revisions": {}}
        if "grades" not in data["persons"][person]:
            data["persons"][person]["grades"] = {}
        if "emergency_revisions" not in data["persons"][person]:
            data["persons"][person]["emergency_revisions"] = {}

    # ── Adaptive grading migration (runs once, then no-ops) ──────────────────
    today_str = format_date_for_storage(datetime.now())
    needs_save = False

    if "adaptive_grading_enabled" not in data:
        data["adaptive_grading_enabled"] = True
        needs_save = True

    if "adaptive_start_date" not in data:
        data["adaptive_start_date"] = today_str
        needs_save = True

    for lecture in data.get("lectures", {}).values():
        normalized_category = _normalize_category(lecture.get("category"))
        if normalized_category != lecture.get("category"):
            lecture["category"] = normalized_category
            needs_save = True
        if "interval_multiplier" not in lecture:
            lecture["interval_multiplier"] = 1.0
            needs_save = True
        if "skip_count" in lecture:
            lecture.pop("skip_count", None)
            needs_save = True

    for person in PERSONS:
        if "skip_counts" not in data["persons"].get(person, {}):
            data["persons"][person]["skip_counts"] = {}
            needs_save = True

    # Wrap legacy string grades into {"grade": ..., "timestamp": <revision_date>}
    # Legacy timestamps are always in the past → adaptive_start_date check skips them
    for person in PERSONS:
        grades = data["persons"].get(person, {}).get("grades", {})
        for grade_key, grade_val in list(grades.items()):
            if isinstance(grade_val, str):
                parts = grade_key.rsplit("_", 1)
                revision_timestamp = "1970-01-01"  # far-past fallback → never adaptive
                if len(parts) == 2:
                    lid, stage = parts
                    rev_dates = data.get("lectures", {}).get(lid, {}).get("revision_dates", {})
                    if stage in rev_dates:
                        revision_timestamp = rev_dates[stage]
                grades[grade_key] = {"grade": grade_val, "timestamp": revision_timestamp}
                needs_save = True

    if needs_save:
        save_data(data)
    # ── End adaptive migration ────────────────────────────────────────────────

    return data


# =======================
# ADAPTIVE LOGIC HELPERS
# =======================
def _apply_fail_logic(data, person, lecture_id, stage, today_str, adaptive_start, prev_grade_entry=None):
    """Tighten interval_multiplier, insert emergency revision, double-tighten on consecutive FAIL."""
    lecture = data["lectures"].get(lecture_id)
    if not lecture:
        return

    lecture["interval_multiplier"] = round(lecture.get("interval_multiplier", 1.0) * 0.85, 4)

    # Extra tightening if previous NEW grade for same stage was also FAIL
    if prev_grade_entry is not None:
        prev_val = get_grade_value(prev_grade_entry)
        prev_ts = prev_grade_entry.get("timestamp", "1970-01-01") if isinstance(prev_grade_entry, dict) else "1970-01-01"
        if prev_val == "FAIL" and prev_ts >= adaptive_start:
            lecture["interval_multiplier"] = round(lecture["interval_multiplier"] * 0.85, 4)

    # Insert emergency revision at +2 days
    emergency_date = datetime.strptime(today_str, "%Y-%m-%d") + timedelta(days=2)
    emergency_key = f"{lecture_id}_{stage}_emergency"
    data["persons"][person]["emergency_revisions"][emergency_key] = format_date_for_storage(emergency_date)


def _apply_partial_logic(data, lecture_id, stage):
    """Tighten interval_multiplier and pull next revision 20% closer."""
    lecture = data["lectures"].get(lecture_id)
    if not lecture:
        return

    lecture["interval_multiplier"] = round(lecture.get("interval_multiplier", 1.0) * 0.9, 4)

    stage_order = ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]
    if stage in stage_order:
        current_idx = stage_order.index(stage)
        if current_idx + 1 < len(stage_order):
            next_stage = stage_order[current_idx + 1]
            if next_stage in lecture["revision_dates"]:
                next_date_str = lecture["revision_dates"][next_stage]
                today = datetime.now().date()
                next_date = datetime.strptime(next_date_str, "%Y-%m-%d").date()
                days_until = (next_date - today).days
                if days_until > 1:
                    new_days = max(1, int(days_until * 0.8))
                    lecture["revision_dates"][next_stage] = format_date_for_storage(
                        today + timedelta(days=new_days)
                    )


def _apply_perfect_logic(data, person, lecture_id, adaptive_start, prev_grade_entry=None):
    """Relax interval_multiplier on PERFECT streak and reset skip_count."""
    lecture = data["lectures"].get(lecture_id)
    if not lecture:
        return

    data["persons"][person].setdefault("skip_counts", {})[lecture_id] = 0

    if prev_grade_entry is not None:
        prev_val = get_grade_value(prev_grade_entry)
        prev_ts = prev_grade_entry.get("timestamp", "1970-01-01") if isinstance(prev_grade_entry, dict) else "1970-01-01"
        if prev_val == "PERFECT" and prev_ts >= adaptive_start:
            lecture["interval_multiplier"] = round(lecture.get("interval_multiplier", 1.0) * 1.1, 4)


def save_data(data):
    """Save data to GitHub JSON file"""
    print("[GitHub] save_data called")
    headers = _github_headers()
    if not headers:
        print("[GitHub] save_data aborted: missing auth header")
        return False

    json_string = json.dumps(data, indent=2)

    try:
        get_response = requests.get(
            GITHUB_API_URL,
            headers=headers,
            params={"ref": GITHUB_BRANCH, "ts": int(time.time())},
            timeout=10
        )
    except requests.RequestException:
        return False

    sha = None
    if get_response.ok:
        existing_payload = get_response.json()
        sha = existing_payload.get("sha")
        existing_content = existing_payload.get("content", "")
        if existing_content:
            try:
                existing_decoded = base64.b64decode(existing_content).decode("utf-8")
                if existing_decoded == json_string:
                    print("[GitHub] save_data skipped: no changes")
                    return True
            except (ValueError, json.JSONDecodeError):
                pass
    elif get_response.status_code != 404:
        _log_github_error("GET (sha)", get_response)
        return False

    content_b64 = base64.b64encode(json_string.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "update gk data",
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    def _put_with_payload(payload_to_send):
        try:
            return requests.put(
                GITHUB_API_URL,
                headers=headers,
                json=payload_to_send,
                timeout=10
            )
        except requests.RequestException:
            return None

    put_response = _put_with_payload(payload)
    if put_response is None:
        return False

    if put_response.ok:
        new_sha = put_response.json().get("content", {}).get("sha")
        print(f"[GitHub] save_data succeeded, new sha: {new_sha}")
        return True

    if put_response.status_code in (409, 422):
        try:
            retry_get = requests.get(
                GITHUB_API_URL,
                headers=headers,
                params={"ref": GITHUB_BRANCH, "ts": int(time.time())},
                timeout=10
            )
        except requests.RequestException:
            _log_github_error("PUT", put_response)
            return False

        if not retry_get.ok:
            _log_github_error("GET (retry)", retry_get)
            _log_github_error("PUT", put_response)
            return False

        retry_payload = retry_get.json()
        retry_sha = retry_payload.get("sha")
        if not retry_sha:
            _log_github_error("PUT", put_response)
            return False

        payload["sha"] = retry_sha
        put_response = _put_with_payload(payload)
        if put_response is None:
            return False
        if not put_response.ok:
            _log_github_error("PUT (retry)", put_response)
            return False
        new_sha = put_response.json().get("content", {}).get("sha")
        print(f"[GitHub] save_data succeeded, new sha: {new_sha}")
        return True

    _log_github_error("PUT", put_response)
    return False


def calculate_revision_dates(study_date_str, exam_date_str, difficulty, interval_multiplier=1.0):
    """Calculate R1-R7 dates based on ratios, difficulty, and interval multiplier"""
    if not exam_date_str:
        return {}

    study_date = datetime.strptime(study_date_str, "%Y-%m-%d")
    exam_date = datetime.strptime(exam_date_str, "%Y-%m-%d")

    T = (exam_date - study_date).days

    if T <= 0:
        return {}

    # Difficulty tightens/loosens gaps (1=loose, 5=tight)
    # Higher difficulty means more frequent revisions (smaller multiplier)
    difficulty_factor = 1.0 + (3 - difficulty) * 0.15

    revision_dates = {}
    stages_created = 0

    for stage, ratio in REVISION_RATIOS.items():
        days_offset = int(T * ratio * difficulty_factor * interval_multiplier)
        revision_date = study_date + timedelta(days=days_offset)

        # Hard ceiling: no revision may exceed exam date
        if revision_date > exam_date:
            break

        revision_dates[stage] = format_date_for_storage(revision_date)
        stages_created += 1

    return revision_dates


def get_todays_revisions(data, person):
    """Get all revisions due today for a person, including emergency revisions."""
    today = datetime.now().date()
    todays_revisions = []
    person_data = data["persons"][person]
    emergency_revisions = person_data.get("emergency_revisions", {})

    for lecture_id, lecture in data["lectures"].items():
        for stage, date_str in lecture["revision_dates"].items():
            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            grade_key = f"{lecture_id}_{stage}"
            grade = person_data["grades"].get(grade_key)

            if not grade and revision_date == today:
                todays_revisions.append({
                    "lecture_id": lecture_id,
                    "lecture_name": lecture["name"],
                    "stage": stage,
                    "date": format_date_for_display(date_str),
                    "difficulty": lecture["difficulty"],
                    "category": lecture["category"],
                    "date_str": date_str,
                    "is_emergency": False
                })

        lecture_prefix = f"{lecture_id}_"
        for emergency_key, date_str in emergency_revisions.items():
            if not emergency_key.startswith(lecture_prefix) or not emergency_key.endswith("_emergency"):
                continue

            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            grade = person_data["grades"].get(emergency_key)
            if grade or revision_date != today:
                continue

            base_stage = emergency_key[len(lecture_prefix):-len("_emergency")]
            todays_revisions.append({
                "lecture_id": lecture_id,
                "lecture_name": lecture["name"],
                "stage": f"{base_stage} (Emergency)",
                "date": format_date_for_display(date_str),
                "difficulty": lecture["difficulty"],
                "category": lecture["category"],
                "date_str": date_str,
                "is_emergency": True
            })

    stage_order = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5, "R6": 6, "R7": 7}
    todays_revisions.sort(
        key=lambda x: (
            stage_order.get(x["stage"].split()[0], 9),
            1 if "(Emergency)" in x["stage"] else 0,
            x["lecture_name"]
        )
    )
    return todays_revisions



def get_missed_revisions(data, person):
    """Get all missed revisions (date < today with no grade), including emergencies."""
    today = datetime.now().date()
    missed_revisions = []
    person_data = data["persons"][person]
    emergency_revisions = person_data.get("emergency_revisions", {})

    for lecture_id, lecture in data["lectures"].items():
        for stage, date_str in lecture["revision_dates"].items():
            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            grade_key = f"{lecture_id}_{stage}"
            grade = person_data["grades"].get(grade_key)

            if not grade and revision_date < today:
                overdue_days = (today - revision_date).days
                missed_revisions.append({
                    "lecture_id": lecture_id,
                    "lecture_name": lecture["name"],
                    "stage": stage,
                    "date": format_date_for_display(date_str),
                    "overdue_days": overdue_days,
                    "difficulty": lecture["difficulty"],
                    "category": lecture["category"],
                    "date_str": date_str,
                    "is_emergency": False
                })

        lecture_prefix = f"{lecture_id}_"
        for emergency_key, date_str in emergency_revisions.items():
            if not emergency_key.startswith(lecture_prefix) or not emergency_key.endswith("_emergency"):
                continue

            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            grade = person_data["grades"].get(emergency_key)
            if grade or revision_date >= today:
                continue

            base_stage = emergency_key[len(lecture_prefix):-len("_emergency")]
            overdue_days = (today - revision_date).days
            missed_revisions.append({
                "lecture_id": lecture_id,
                "lecture_name": lecture["name"],
                "stage": f"{base_stage} (Emergency)",
                "date": format_date_for_display(date_str),
                "overdue_days": overdue_days,
                "difficulty": lecture["difficulty"],
                "category": lecture["category"],
                "date_str": date_str,
                "is_emergency": True
            })

    stage_order = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5, "R6": 6, "R7": 7}
    missed_revisions.sort(
        key=lambda x: (
            -x["overdue_days"],
            stage_order.get(x["stage"].split()[0], 9),
            1 if "(Emergency)" in x["stage"] else 0,
            x["lecture_name"]
        )
    )
    return missed_revisions


def grade_revision(data, person, lecture_id, stage, grade):
    """Grade a revision for a person with adaptive scheduling behavior."""
    st.session_state.last_graded_key = f"{lecture_id}_{stage}"
    st.session_state.last_graded_person = person

    today = datetime.now().date()
    today_str = format_date_for_storage(today)
    lecture = data["lectures"].get(lecture_id, {})
    person_data = data["persons"][person]
    emergency_revisions = person_data.setdefault("emergency_revisions", {})
    is_emergency = stage.endswith(" (Emergency)")
    base_stage = stage.replace(" (Emergency)", "")
    standard_grade_key = f"{lecture_id}_{base_stage}"
    emergency_grade_key = f"{lecture_id}_{base_stage}_emergency"
    storage_grade_key = emergency_grade_key if is_emergency else standard_grade_key
    previous_grade_key = standard_grade_key if is_emergency else storage_grade_key
    adaptive_start = data.get("adaptive_start_date", today_str)
    adaptive_active = data.get("adaptive_grading_enabled", True) and today_str >= adaptive_start

    if grade == "SKIP" and adaptive_active:
        skip_counts = person_data.setdefault("skip_counts", {})
        skip_counts[lecture_id] = skip_counts.get(lecture_id, 0) + 1

        if is_emergency:
            current_date_str = emergency_revisions.get(emergency_grade_key)
            if current_date_str:
                new_date = datetime.strptime(current_date_str, "%Y-%m-%d") + timedelta(days=1)
                emergency_revisions[emergency_grade_key] = format_date_for_storage(new_date)
        else:
            current_date_str = lecture.get("revision_dates", {}).get(base_stage)
            if current_date_str:
                new_date = datetime.strptime(current_date_str, "%Y-%m-%d") + timedelta(days=1)
                lecture["revision_dates"][base_stage] = format_date_for_storage(new_date)

        if skip_counts[lecture_id] >= 3:
            prev_grade_entry = person_data["grades"].get(previous_grade_key)
            skip_counts[lecture_id] = 0
            if is_emergency:
                emergency_revisions.pop(emergency_grade_key, None)
            _apply_fail_logic(data, person, lecture_id, base_stage, today_str, adaptive_start, prev_grade_entry)
            reflow_revisions(data, lecture_id, person=person)

        save_ok = save_data(data)
        if not save_ok:
            fresh_data = load_data()
            fresh_data["lectures"][lecture_id] = data["lectures"][lecture_id]
            fresh_person = fresh_data["persons"][person]
            fresh_person["emergency_revisions"] = person_data["emergency_revisions"]
            fresh_person["skip_counts"] = person_data.get("skip_counts", {})
            save_ok = save_data(fresh_data)
        return

    prev_grade_entry = person_data["grades"].get(previous_grade_key)

    if is_emergency:
        emergency_revisions.pop(emergency_grade_key, None)

    person_data["grades"][storage_grade_key] = {"grade": grade, "timestamp": today_str}

    if adaptive_active:
        if grade == "FAIL":
            person_data.setdefault("skip_counts", {})[lecture_id] = 0
            _apply_fail_logic(data, person, lecture_id, base_stage, today_str, adaptive_start, prev_grade_entry)
            reflow_revisions(data, lecture_id, person=person)
        elif grade == "PARTIAL":
            stage_order = ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]
            next_stage = None
            _apply_partial_logic(data, lecture_id, base_stage)
            reflow_revisions(data, lecture_id, person=person)
            if base_stage in stage_order:
                current_idx = stage_order.index(base_stage)
                if current_idx + 1 < len(stage_order):
                    next_stage = stage_order[current_idx + 1]
            if next_stage and next_stage in lecture.get("revision_dates", {}):
                next_grade_key = f"{lecture_id}_{next_stage}"
                next_date = datetime.strptime(lecture["revision_dates"][next_stage], "%Y-%m-%d").date()
                next_has_grade = any(
                    data["persons"][name]["grades"].get(next_grade_key)
                    for name in PERSONS
                    if name in data["persons"]
                )
                if not next_has_grade and next_date >= today:
                    days_until = (next_date - today).days
                    new_days = max(1, int(days_until * 0.8))
                    lecture["revision_dates"][next_stage] = format_date_for_storage(
                        today + timedelta(days=new_days)
                    )
        elif grade == "PERFECT":
            _apply_perfect_logic(data, person, lecture_id, adaptive_start, prev_grade_entry)
            reflow_revisions(data, lecture_id, person=person)

    save_ok = save_data(data)
    if not save_ok:
        fresh_data = load_data()
        fresh_data["lectures"][lecture_id] = data["lectures"][lecture_id]
        fresh_person = fresh_data["persons"][person]
        fresh_person["grades"][storage_grade_key] = person_data["grades"][storage_grade_key]
        fresh_person["emergency_revisions"] = person_data["emergency_revisions"]
        fresh_person["skip_counts"] = person_data.get("skip_counts", {})
        save_ok = save_data(fresh_data)

    verified = False
    if save_ok:
        for _ in range(3):
            verify_data = load_data()
            stored = verify_data["persons"][person]["grades"].get(storage_grade_key)
            verified = get_grade_value(stored) == grade
            if verified:
                break
            time.sleep(0.4)
    print(f"[GitHub] grade verify: {verified}")


def reflow_revisions(data, lecture_id, person=None):
    """Reflow only future ungraded standard revisions for a lecture.

    If person is provided, only that person's graded stages are treated as locked.
    Otherwise (manual/edit reflows), any person's graded stage is locked.
    """
    lecture = data["lectures"][lecture_id]

    if not data["exam_date"]:
        return

    today = datetime.now().date()
    current_dates = lecture.get("revision_dates", {})
    recalculated_dates = calculate_revision_dates(
        lecture["study_date"],
        data["exam_date"],
        lecture["difficulty"],
        lecture.get("interval_multiplier", 1.0)
    )

    merged_dates = {}
    for stage, current_date_str in current_dates.items():
        current_date = datetime.strptime(current_date_str, "%Y-%m-%d").date()
        grade_key = f"{lecture_id}_{stage}"
        if person is not None:
            stage_has_grade = bool(
                data["persons"].get(person, {}).get("grades", {}).get(grade_key)
            )
        else:
            stage_has_grade = any(
                data["persons"].get(person_name, {}).get("grades", {}).get(grade_key)
                for person_name in PERSONS
            )

        if current_date < today or stage_has_grade:
            merged_dates[stage] = current_date_str
        elif stage in recalculated_dates:
            merged_dates[stage] = recalculated_dates[stage]
        else:
            merged_dates[stage] = current_date_str

    for stage, new_date_str in recalculated_dates.items():
        if stage not in merged_dates:
            merged_dates[stage] = new_date_str

    lecture["revision_dates"] = {
        stage: merged_dates[stage]
        for stage in REVISION_RATIOS
        if stage in merged_dates
    }
    save_data(data)
    # After reflow: do NOT auto-run global_balance here. Use manual "⚖️ Fix Schedule" button.


def recalculate_pending_revisions(data, lecture_id):
    """Reset only pending standard revisions to baseline schedule for a lecture.

    Completed stage dates are preserved. Pending stages are recalculated from
    study_date + difficulty + exam ceiling with interval_multiplier reset to 1.0.
    """
    lecture = data["lectures"].get(lecture_id)
    if not lecture or not data.get("exam_date"):
        return False

    current_dates = lecture.get("revision_dates", {})
    baseline_dates = calculate_revision_dates(
        lecture["study_date"],
        data["exam_date"],
        lecture["difficulty"],
        1.0
    )

    merged_dates = {}
    for stage in REVISION_RATIOS:
        current_date = current_dates.get(stage)
        stage_key = f"{lecture_id}_{stage}"
        stage_completed = any(
            data["persons"].get(person_name, {}).get("grades", {}).get(stage_key)
            for person_name in PERSONS
        )

        if stage_completed and current_date:
            merged_dates[stage] = current_date
        elif stage in baseline_dates:
            merged_dates[stage] = baseline_dates[stage]

    lecture["revision_dates"] = merged_dates
    lecture["interval_multiplier"] = 1.0

    # Clear pending emergency revisions for this lecture after manual reset.
    lecture_prefix = f"{lecture_id}_"
    for person_name in PERSONS:
        person_data = data["persons"].get(person_name, {})
        emergency_map = person_data.get("emergency_revisions", {})
        keys_to_remove = [
            key for key in emergency_map.keys()
            if key.startswith(lecture_prefix) and key.endswith("_emergency")
        ]
        for key in keys_to_remove:
            del emergency_map[key]

    return save_data(data)


def global_balance(data, person):
    """Global load balancing scheduler for a single person.

    - Collects all pending revisions (today, missed, future ungraded, emergencies)
    - Prioritizes by emergency, overdue days, and stage weight
    - Redistributes revisions starting today with max 6/day up to exam_date
    - Preserves any completed/graded revisions (by any person)
    """
    if not data or not data.get("exam_date"):
        return False

    today = datetime.now().date()
    exam_date = datetime.strptime(data["exam_date"], "%Y-%m-%d").date()
    if today > exam_date:
        return False

    person_data = data["persons"].setdefault(person, {"grades": {}, "emergency_revisions": {}})

    # NOTE: `lecture["revision_dates"]` are shared across persons.
    # Future improvement: move revision_dates to per-person storage to avoid cross-person side-effects.

    # Stage weights
    stage_weights = {
        "R1": 10,
        "R2": 9,
        "R3": 8,
        "R4": 6,
        "R5": 4,
        "R6": 2,
        "R7": 1
    }

    pending = []  # items to schedule
    pending_standard_keys = set()
    pending_emergency_keys = set()

    # Collect pending standard revisions (skip any stage that has a grade by ANY person)
    for lecture_id, lecture in data.get("lectures", {}).items():
        for stage, date_str in lecture.get("revision_dates", {}).items():
            grade_key = f"{lecture_id}_{stage}"
            # If any person has graded this stage, preserve it
            stage_completed = any(
                data["persons"].get(p, {}).get("grades", {}).get(grade_key)
                for p in PERSONS
            )
            if stage_completed:
                continue

            # Pending standard stage
            try:
                scheduled_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                scheduled_date = today

            overdue_days = max(0, (today - scheduled_date).days)
            # Priority: stage weight emphasized to favor early stages
            priority = 0
            priority += overdue_days * 3
            priority += stage_weights.get(stage, 0) * 2

            pending.append({
                "lecture_id": lecture_id,
                "stage": stage,
                "is_emergency": False,
                "priority": priority,
                "current_date": scheduled_date
            })
            pending_standard_keys.add(grade_key)

    # Collect pending emergencies for this person. Deduplicate multiple emergencies per lecture.
    emergency_map = person_data.setdefault("emergency_revisions", {})
    emerg_by_lecture = {}
    for ekey, date_str in list(emergency_map.items()):
        if not ekey.endswith("_emergency"):
            continue
        # split base to get lecture_id and stage
        base = ekey[:-len("_emergency")]
        if "_" not in base:
            continue
        lecture_id_part, base_stage = base.rsplit("_", 1)
        lecture_id = lecture_id_part

        # If this emergency is already graded for this person, treat as locked
        if person_data.get("grades", {}).get(ekey):
            continue

        emerg_by_lecture.setdefault(lecture_id, []).append((ekey, date_str, base_stage))

    for lecture_id, entries in emerg_by_lecture.items():
        # choose earliest emergency date to keep
        entries_sorted = sorted(entries, key=lambda x: x[1])
        chosen_key, chosen_date_str, chosen_stage = entries_sorted[0]
        try:
            scheduled_date = datetime.strptime(chosen_date_str, "%Y-%m-%d").date()
        except Exception:
            scheduled_date = today

        overdue_days = max(0, (today - scheduled_date).days)
        # Emergency bonus plus overdue and stage weight (stage weight doubled)
        priority = 0
        priority += 100
        priority += overdue_days * 3
        priority += stage_weights.get(chosen_stage, 0) * 2

        pending.append({
            "lecture_id": lecture_id,
            "stage": chosen_stage,
            "is_emergency": True,
            "priority": priority,
            "current_date": scheduled_date,
            "emergency_key": chosen_key
        })
        pending_emergency_keys.add(chosen_key)

        # Remove duplicate emergency keys for the same lecture (keep only chosen)
        for other in entries_sorted[1:]:
            other_key = other[0]
            # Only remove if not graded
            if other_key in emergency_map and not person_data.get("grades", {}).get(other_key):
                try:
                    del emergency_map[other_key]
                except KeyError:
                    pass

    # Baseline occupancy: count all scheduled revisions for this person that are NOT pending
    # If nothing pending, bail out early
    if not pending:
        return False
    occupancy = {}

    def _inc_occupancy(d):
        occupancy[d] = occupancy.get(d, 0) + 1

    for lecture_id, lecture in data.get("lectures", {}).items():
        for stage, date_str in lecture.get("revision_dates", {}).items():
            grade_key = f"{lecture_id}_{stage}"
            if grade_key in pending_standard_keys:
                continue
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                continue
            _inc_occupancy(d)

    for ekey, date_str in emergency_map.items():
        if ekey in pending_emergency_keys:
            continue
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            continue
        _inc_occupancy(d)

    # Sort pending by priority descending (higher -> schedule earlier)
    pending.sort(key=lambda x: -x["priority"])

    # Sequentially assign pending items starting today, max 6/day, clamp to exam_date
    for item in pending:
        assign_date = None
        d = today
        while d <= exam_date:
            if occupancy.get(d, 0) < 6:
                assign_date = d
                break
            d = d + timedelta(days=1)

        if assign_date is None:
            # no free day found — place on exam_date (clamp)
            assign_date = exam_date

        new_date_str = format_date_for_storage(assign_date)

        if item.get("is_emergency"):
            # Update emergency mapping for person
            emergency_map[item["emergency_key"]] = new_date_str
        else:
            # Update lecture revision date (shared across persons) only for pending stages
            lecture = data.get("lectures", {}).get(item["lecture_id"])
            if lecture and item["stage"] in lecture.get("revision_dates", {}):
                lecture["revision_dates"][item["stage"]] = new_date_str

        _inc_occupancy(assign_date)

    # Save changes
    save_data(data)
    return True


def get_backlog_count(data, person):
    """Return count of missed + overdue + pending revisions for a person."""
    if not data or not data.get("exam_date"):
        return 0

    today = datetime.now().date()
    person_data = data["persons"].get(person, {})
    count = 0

    # Count standard revisions
    for lecture_id, lecture in data.get("lectures", {}).items():
        for stage, date_str in lecture.get("revision_dates", {}).items():
            grade_key = f"{lecture_id}_{stage}"
            # skip if graded for this person
            if person_data.get("grades", {}).get(grade_key):
                continue
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                d = today
            if d < today:
                count += 1
            else:
                count += 1

    # Count emergency revisions for this person (only ungraded)
    for ekey, date_str in person_data.get("emergency_revisions", {}).items():
        if person_data.get("grades", {}).get(ekey):
            continue
        count += 1

    return count


def get_revisions_for_date(data, person, selected_date):
    """Get all revisions scheduled for a specific date for a person, including emergencies."""
    revisions = []
    person_data = data["persons"][person]
    emergency_revisions = person_data.get("emergency_revisions", {})

    for lecture_id, lecture in data["lectures"].items():
        for stage, date_str in lecture["revision_dates"].items():
            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            grade_key = f"{lecture_id}_{stage}"
            grade = person_data["grades"].get(grade_key)

            if revision_date == selected_date:
                revisions.append({
                    "lecture_id": lecture_id,
                    "lecture_name": lecture["name"],
                    "stage": stage,
                    "date": format_date_for_display(date_str),
                    "difficulty": lecture["difficulty"],
                    "category": lecture["category"],
                    "date_str": date_str,
                    "grade": grade,
                    "is_emergency": False
                })

        lecture_prefix = f"{lecture_id}_"
        for emergency_key, date_str in emergency_revisions.items():
            if not emergency_key.startswith(lecture_prefix) or not emergency_key.endswith("_emergency"):
                continue

            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if revision_date != selected_date:
                continue

            base_stage = emergency_key[len(lecture_prefix):-len("_emergency")]
            revisions.append({
                "lecture_id": lecture_id,
                "lecture_name": lecture["name"],
                "stage": f"{base_stage} (Emergency)",
                "date": format_date_for_display(date_str),
                "difficulty": lecture["difficulty"],
                "category": lecture["category"],
                "date_str": date_str,
                "grade": person_data["grades"].get(emergency_key),
                "is_emergency": True
            })

    stage_order = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5, "R6": 6, "R7": 7}
    revisions.sort(
        key=lambda x: (
            stage_order.get(x["stage"].split()[0], 9),
            1 if "(Emergency)" in x["stage"] else 0,
            x["lecture_name"]
        )
    )
    return revisions


# =======================
# VIEW: Home / Today
# =======================
def view_home():
    st.title("🏠 Today's Revisions")
    
    data = load_data()
    apply_overdue_auto_fail(data, st.session_state.current_person)
    # Exam Date at top
    col1, col2 = st.columns([2, 1])
    with col1:
        exam_date_input = st.date_input(
            "📅 Exam Date",
            value=datetime.strptime(data["exam_date"], "%Y-%m-%d").date() if data["exam_date"] else None,
            key="exam_date_input",
            format="DD/MM/YYYY"
        )
        
        if exam_date_input:
            new_exam_date = format_date_for_storage(exam_date_input)
            if data["exam_date"] != new_exam_date:
                data["exam_date"] = new_exam_date
                save_data(data)
                # Reflow all lectures
                for lecture_id in data["lectures"].keys():
                    reflow_revisions(data, lecture_id)
                st.success("Exam date updated! All revisions reflowed.")
    
    with col2:
        st.metric("Days Until Exam", 
                 (exam_date_input - datetime.now().date()).days if exam_date_input else "N/A")
    
    st.divider()
    
    # Person Selector
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        if st.button("👨 Harsh", use_container_width=True, 
                    type="primary" if st.session_state.current_person == "Harsh" else "secondary"):
            st.session_state.current_person = "Harsh"
            st.rerun()
    with col2:
        if st.button("👩 Divya", use_container_width=True,
                    type="primary" if st.session_state.current_person == "Divya" else "secondary"):
            st.session_state.current_person = "Divya"
            st.rerun()
    
    st.subheader(f"Revisions for {st.session_state.current_person}")
    if st.button("⚖️ Fix Schedule"):
        try:
            global_balance(data, st.session_state.current_person)
            st.success("Schedule optimized!")
            st.rerun()
        except Exception:
            st.error("Could not optimize schedule right now.")

    todays = get_todays_revisions(data, st.session_state.current_person)

    if todays:
        st.write(f"**{len(todays)} revision(s) due today:**")

        for idx, rev in enumerate(todays):
            with st.container():
                st.markdown(f"### {rev['lecture_name']}")
                if rev.get("is_emergency"):
                    st.markdown('<span class="emergency-chip">EMERGENCY REVISION</span>', unsafe_allow_html=True)
                col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
                
                with col1:
                    st.write(f"**Stage:** {rev['stage']}")
                    st.write(f"**Category:** {rev['category']}")
                    st.write(f"**Difficulty:** {rev['difficulty']}/5")
                
                button_key_base = f"today_{rev['lecture_id']}_{rev['stage']}"

                with col2:
                    st.button(
                        "❌ FAIL",
                        key=f"fail_{button_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "FAIL"
                        )
                    )
                
                with col3:
                    st.button(
                        "⚠️ PARTIAL",
                        key=f"partial_{button_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "PARTIAL"
                        )
                    )
                
                with col4:
                    st.button(
                        "✅ PERFECT",
                        key=f"perfect_{button_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "PERFECT"
                        )
                    )
                
                with col5:
                    st.button(
                        "⏭️ SKIP",
                        key=f"skip_{button_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "SKIP"
                        )
                    )
                
                st.divider()
    else:
        st.info("🎉 No revisions due today! Well done!")

    missed = get_missed_revisions(data, st.session_state.current_person)
    total_missed = len(missed)

    if total_missed >= 5:
        # display_missed = missed[:3]
        display_missed = missed
        st.warning(f"⚠ Recovery Mode Active — Showing 3 most critical overdue revisions. {total_missed} ")
    else:
        display_missed = missed

    if display_missed:
        if total_missed < 5:
            st.warning(f"⚠️ **{total_missed} missed revision(s):**")

        for idx, rev in enumerate(display_missed):
            with st.expander(f"{rev['lecture_name']} - {rev['stage']} ({rev['overdue_days']} days overdue)"):
                if rev.get("is_emergency"):
                    st.markdown('<span class="emergency-chip">EMERGENCY REVISION</span>', unsafe_allow_html=True)
                col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])

                with col1:
                    st.write(f"**Due Date:** {rev['date']}")
                    st.write(f"**Category:** {rev['category']}")

                missed_key_base = f"missed_{rev['lecture_id']}_{rev['stage']}"
                with col2:
                    st.button(
                        "❌ FAIL",
                        key=f"missed_fail_{missed_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "FAIL"
                        )
                    )

                with col3:
                    st.button(
                        "⚠️ PARTIAL",
                        key=f"missed_partial_{missed_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "PARTIAL"
                        )
                    )

                with col4:
                    st.button(
                        "✅ PERFECT",
                        key=f"missed_perfect_{missed_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "PERFECT"
                        )
                    )

                with col5:
                    st.button(
                        "⏭️ SKIP",
                        key=f"missed_skip_{missed_key_base}",
                        use_container_width=True,
                        on_click=grade_revision,
                        args=(
                            data,
                            st.session_state.current_person,
                            rev["lecture_id"],
                            rev["stage"],
                            "SKIP"
                        )
                    )


# =======================
# VIEW: Add Lecture
# =======================
def view_add_lecture():
    st.title("➕ Add New Lecture")
    
    data = load_data()
    
    if not data["exam_date"]:
        st.error("⚠️ Please set an exam date in the Home view first!")
        return
    
    exam_date = datetime.strptime(data["exam_date"], "%Y-%m-%d")
    days_until_exam = (exam_date.date() - datetime.now().date()).days
    
    if days_until_exam < 30:
        st.error("❌ Cannot add lectures in the last 30 days before exam!")
        return
    
    with st.form("add_lecture_form"):
        lecture_name = st.text_input("Lecture Name", placeholder="e.g., Mughal Empire")
        
        study_date = st.date_input(
            "Study Date",
            max_value=exam_date.date(),
            format="DD/MM/YYYY"
        )
        
        difficulty = st.slider("Difficulty (1=Easy, 5=Hard)", 1, 5, 3)
        
        category = st.selectbox("Category", CATEGORIES)
        
        submitted = st.form_submit_button("Add Lecture for Both Persons")
        
        if submitted:
            if not lecture_name:
                st.error("Please enter a lecture name!")
            else:
                # Create unique lecture ID
                lecture_id = f"lecture_{datetime.now().timestamp()}"
                
                # Calculate revision dates
                revision_dates = calculate_revision_dates(
                    format_date_for_storage(study_date),
                    data["exam_date"],
                    difficulty
                )
                
                # Add lecture (affects both persons)
                data["lectures"][lecture_id] = {
                    "name": lecture_name,
                    "study_date": format_date_for_storage(study_date),
                    "difficulty": difficulty,
                    "category": category,
                    "revision_dates": revision_dates,
                    "interval_multiplier": 1.0
                }
                
                save_data(data)
                st.success(f"✅ Lecture '{lecture_name}' added for both Harsh and Divya!")
                st.info(f"📅 Generated {len(revision_dates)} revision stages: {', '.join(revision_dates.keys())}")


# =======================
# VIEW: Daily Schedule
# =======================
def view_daily_schedule():
    st.title("📅 Daily Schedule")
    
    data = load_data()
    
    # Person Selector
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        if st.button("👨 Harsh", key="schedule_harsh", use_container_width=True,
                    type="primary" if st.session_state.current_person == "Harsh" else "secondary"):
            st.session_state.current_person = "Harsh"
            st.rerun()
    with col2:
        if st.button("👩 Divya", key="schedule_divya", use_container_width=True,
                    type="primary" if st.session_state.current_person == "Divya" else "secondary"):
            st.session_state.current_person = "Divya"
            st.rerun()
    
    st.divider()
    
    # Date picker
    selected_date = st.date_input(
        "Select a Date",
        value=datetime.now().date(),
        format="DD/MM/YYYY"
    )
    
    st.divider()
    
    # Get revisions for selected date
    revisions = get_revisions_for_date(data, st.session_state.current_person, selected_date)
    
    # Display the date in a friendly format
    date_display = selected_date.strftime("%A, %d %B %Y")
    st.subheader(f"Revisions for {date_display}")
    st.write(f"for **{st.session_state.current_person}**")
    
    if revisions:
        st.write(f"📌 **{len(revisions)} revision(s) scheduled:**")
        st.divider()
        
        for rev in revisions:
            with st.container():
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    # Status indicator
                    status = "✅" if rev["grade"] else "⏳"
                    st.markdown(f"### {status} {rev['lecture_name']}")
                    if rev.get("is_emergency"):
                        st.markdown('<span class="emergency-chip">EMERGENCY REVISION</span>', unsafe_allow_html=True)
                    st.write(f"**Stage:** {rev['stage']} | **Category:** {rev['category']} | **Difficulty:** {rev['difficulty']}/5")
                    if rev["grade"]:
                        st.write(f"**Status:** ✓ {get_grade_value(rev['grade'])}")
                
                with col2:
                    button_key_base = f"schedule_{rev['lecture_id']}_{rev['stage']}"
                    
                    if rev["grade"]:
                        # Already graded - show undo
                        if st.button("🔄 Undo", key=f"undo_{button_key_base}", use_container_width=True):
                            grade_key = f"{rev['lecture_id']}_{rev['stage']}"
                            del data["persons"][st.session_state.current_person]["grades"][grade_key]
                            save_data(data)
                            st.rerun()
                    else:
                        # Not graded - show mark as complete
                        if st.button("✅ Mark", key=f"mark_{button_key_base}", use_container_width=True):
                            grade_revision(data, st.session_state.current_person,
                                         rev["lecture_id"], rev["stage"], "PERFECT")
                            st.rerun()
                
                st.divider()
    else:
        st.info(f"🎉 No revisions scheduled for {date_display}!")


# =======================
# VIEW: Full Revision Plan
# =======================
def view_revision_plan():
    st.title("📋 Full Revision Plan")
    
    data = load_data()
    
    # Person Selector
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        if st.button("👨 Harsh", key="plan_harsh", use_container_width=True,
                    type="primary" if st.session_state.current_person == "Harsh" else "secondary"):
            st.session_state.current_person = "Harsh"
            st.rerun()
    with col2:
        if st.button("👩 Divya", key="plan_divya", use_container_width=True,
                    type="primary" if st.session_state.current_person == "Divya" else "secondary"):
            st.session_state.current_person = "Divya"
            st.rerun()
    
    st.subheader(f"Plan for {st.session_state.current_person}")
    
    if not data["lectures"]:
        st.info("No lectures added yet. Go to 'Add Lecture' to get started!")
        return
    
    # Group lectures by category
    lectures_by_category = {}
    for lecture_id, lecture in data["lectures"].items():
        category = _normalize_category(lecture["category"])
        if category not in lectures_by_category:
            lectures_by_category[category] = []
        lectures_by_category[category].append((lecture_id, lecture))
    
    # Create tabs for each category
    category_order = {category: index for index, category in enumerate(CATEGORIES)}
    categories_present = sorted(
        lectures_by_category.keys(),
        key=lambda category: category_order.get(category, len(category_order))
    )
    
    if categories_present:
        tabs = st.tabs([f"📂 {cat.upper()}" for cat in categories_present])
        
        for tab_idx, category in enumerate(categories_present):
            with tabs[tab_idx]:
                # Sort options within each category
                sort_order = st.radio(
                    "Sort by Study Date:",
                    ["Newest First", "Oldest First"],
                    horizontal=True,
                    key=f"sort_order_{category}_{st.session_state.current_person}"
                )
                
                # Sort lectures by study date
                sorted_lectures = sorted(
                    lectures_by_category[category],
                    key=lambda x: x[1]["study_date"],
                    reverse=(sort_order == "Newest First")
                )
                
                st.write(f"**{len(sorted_lectures)} lecture(s) in {category}**")
                st.divider()
                
                # Display lectures in this category
                for lecture_id, lecture in sorted_lectures:
                    lecture_title = f"📚 {lecture['name']:<50} {format_date_compact(lecture['study_date'])}"
                    with st.expander(lecture_title, expanded=False):
                        
                        # Inline editing form
                        with st.form(key=f"edit_form_{lecture_id}"):
                            col1, col2, col3 = st.columns([2, 2, 2])
                            
                            with col1:
                                edit_name = st.text_input("Lecture Name", value=lecture["name"], key=f"name_{lecture_id}")
                                edit_study_date = st.date_input(
                                    "Study Date",
                                    value=datetime.strptime(lecture["study_date"], "%Y-%m-%d").date(),
                                    format="DD/MM/YYYY",
                                    key=f"study_{lecture_id}"
                                )
                            
                            with col2:
                                edit_difficulty = st.slider("Difficulty", 1, 5, lecture["difficulty"], key=f"diff_{lecture_id}")
                                current_category = _normalize_category(lecture["category"])
                                if current_category not in CATEGORIES:
                                    current_category = CATEGORIES[0]
                                edit_category = st.selectbox("Category", CATEGORIES, 
                                                            index=CATEGORIES.index(current_category),
                                                            key=f"cat_{lecture_id}")
                            
                            with col3:
                                col_save, col_delete = st.columns(2)
                                with col_save:
                                    save_changes = st.form_submit_button("💾 Save", use_container_width=True)
                                with col_delete:
                                    delete_lecture = st.form_submit_button("🗑️ Delete", use_container_width=True)
                            
                            if save_changes:
                                # Update lecture fields
                                changed = False
                                if edit_name != lecture["name"]:
                                    lecture["name"] = edit_name
                                    changed = True
                                if format_date_for_storage(edit_study_date) != lecture["study_date"]:
                                    lecture["study_date"] = format_date_for_storage(edit_study_date)
                                    changed = True
                                if edit_difficulty != lecture["difficulty"]:
                                    lecture["difficulty"] = edit_difficulty
                                    changed = True
                                if edit_category != lecture["category"]:
                                    lecture["category"] = edit_category
                                    changed = True
                                
                                if changed:
                                    # Reflow revisions for both persons
                                    reflow_revisions(data, lecture_id)
                                    st.success("✅ Lecture updated and revisions reflowed!")
                                    st.rerun()
                            
                            if delete_lecture:
                                del data["lectures"][lecture_id]
                                # Clean up grades for both persons
                                for person in PERSONS:
                                    grades_to_remove = [k for k in data["persons"][person]["grades"].keys() 
                                                      if k.startswith(lecture_id)]
                                    for k in grades_to_remove:
                                        del data["persons"][person]["grades"][k]
                                save_data(data)
                                st.success("🗑️ Lecture deleted!")
                                st.rerun()
                        
                        st.divider()

                        if st.button(
                            "♻️ Recalculate Pending Revisions",
                            key=f"recalc_pending_{lecture_id}_{st.session_state.current_person}",
                            use_container_width=True
                        ):
                            recalc_ok = recalculate_pending_revisions(data, lecture_id)
                            if recalc_ok:
                                st.success("Pending revisions reset to baseline schedule. Completed stages were preserved.")
                            else:
                                st.error("Could not recalculate pending revisions right now. Please try again.")
                            st.rerun()

                        st.divider()
                        
                        # Revision stages in a grid layout
                        st.write("**Revision Stages:**")
                        st.write("")
                        
                        # Create a grid of revision buttons
                        for stage_idx in range(0, len(lecture["revision_dates"]), 2):
                            cols = st.columns(2)
                            
                            for col_idx, col in enumerate(cols):
                                stage_num = stage_idx + col_idx
                                if stage_num < len(lecture["revision_dates"]):
                                    stage = list(lecture["revision_dates"].keys())[stage_num]
                                    date_str = lecture["revision_dates"][stage]
                                    
                                    with col:
                                        grade_key = f"{lecture_id}_{stage}"
                                        grade = data["persons"][st.session_state.current_person]["grades"].get(grade_key)
                                        
                                        if grade:
                                            # Done - show with grade
                                            button_label = f"{stage}\n{format_date_compact(date_str)}\n✓ {get_grade_value(grade)}"
                                            button_type = "secondary"
                                            
                                            if st.button(button_label, key=f"done_{lecture_id}_{stage}", 
                                                       use_container_width=True, type=button_type):
                                                # Undo: restore date
                                                del data["persons"][st.session_state.current_person]["grades"][grade_key]
                                                save_data(data)
                                                st.rerun()
                                        else:
                                            # Pending - show date
                                            button_label = f"{stage}\n{format_date_compact(date_str)}"
                                            button_type = "primary"
                                            
                                            if st.button(button_label, key=f"pending_{lecture_id}_{stage}",
                                                       use_container_width=True, type=button_type):
                                                # Mark as done (default PERFECT)
                                                grade_revision(data, st.session_state.current_person,
                                                             lecture_id, stage, "PERFECT")
                                                st.rerun()


def apply_overdue_auto_fail(data, person):
    today = datetime.now().date()
    person_data = data["persons"][person]

    for lecture_id, lecture in data["lectures"].items():
        overdue_candidates = []

        for stage, date_str in lecture["revision_dates"].items():
            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            grade_key = f"{lecture_id}_{stage}"

            # Skip already graded
            if person_data["grades"].get(grade_key):
                continue

            overdue_days = (today - revision_date).days

            # softened threshold to avoid aggressive auto-fails (was >7)
            if overdue_days > 13:
                overdue_candidates.append((stage, overdue_days))

        if overdue_candidates:
            # Fail only the most overdue stage
            stage_to_fail = sorted(overdue_candidates, key=lambda x: -x[1])[0][0]
            grade_revision(data, person, lecture_id, stage_to_fail, "FAIL")


# =======================
# MAIN APP
# =======================
def main():
    # Sidebar navigation - force sidebar rendering
    with st.sidebar:
        st.title("📚 SSC GK Tracker")
        
        view = st.radio(
            "Navigation",
            ["🏠 Home / Today", "➕ Add Lecture", "📅 Daily Schedule", "📋 Full Revision Plan"],
            key="navigation"
        )
        
        st.divider()
        st.caption("Built with ❤️ for SSC GK preparation")
    
    if view == "🏠 Home / Today":
        view_home()
    elif view == "➕ Add Lecture":
        view_add_lecture()
    elif view == "📅 Daily Schedule":
        view_daily_schedule()
    elif view == "📋 Full Revision Plan":
        view_revision_plan()


if __name__ == "__main__":
    main()
