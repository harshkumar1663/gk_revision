import streamlit as st
from datetime import datetime, timedelta
import json
import os
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
CATEGORIES = ["History", "Geography", "Polity", "Economy", "Science", "Current Affairs", "Miscellaneous"]

# Use relative path for data file (works both locally and on Streamlit Cloud)
DATA_FILE = Path(__file__).parent.parent / "gk_data.json"

# GitHub storage configuration
GITHUB_OWNER = "harshkumar1663"
GITHUB_REPO = "gk_revision_data"
GITHUB_BRANCH = "main"
GITHUB_FILE_PATH = "gk_data.json"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

# Date formatting helpers
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


def _github_headers():
    try:
        token = st.secrets.get("GITHUB_TOKEN")
    except Exception:
        token = None
    if not token:
        print("[GitHub] Missing GITHUB_TOKEN in Streamlit secrets.")
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "streamlit-gk-revision-app"
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
            params={"ref": GITHUB_BRANCH},
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
    
    return data


def save_data(data):
    """Save data to GitHub JSON file"""
    headers = _github_headers()
    if not headers:
        return

    json_string = json.dumps(data, indent=2)

    try:
        get_response = requests.get(
            GITHUB_API_URL,
            headers=headers,
            params={"ref": GITHUB_BRANCH},
            timeout=10
        )
    except requests.RequestException:
        return

    sha = None
    if get_response.ok:
        existing_payload = get_response.json()
        sha = existing_payload.get("sha")
        existing_content = existing_payload.get("content", "")
        if existing_content:
            try:
                existing_decoded = base64.b64decode(existing_content).decode("utf-8")
                if existing_decoded == json_string:
                    return
            except (ValueError, json.JSONDecodeError):
                pass
    elif get_response.status_code != 404:
        _log_github_error("GET (sha)", get_response)
        return

    content_b64 = base64.b64encode(json_string.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "update gk data",
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    try:
        put_response = requests.put(
            GITHUB_API_URL,
            headers=headers,
            json=payload,
            timeout=10
        )
    except requests.RequestException:
        return

    if not put_response.ok:
        _log_github_error("PUT", put_response)
        return


def calculate_revision_dates(study_date_str, exam_date_str, difficulty):
    """Calculate R1-R7 dates based on ratios and difficulty"""
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
        days_offset = int(T * ratio * difficulty_factor)
        revision_date = study_date + timedelta(days=days_offset)
        
        # Hard ceiling: no revision may exceed exam date
        if revision_date > exam_date:
            break
        
        revision_dates[stage] = format_date_for_storage(revision_date)
        stages_created += 1
    
    return revision_dates


def get_todays_revisions(data, person):
    """Get all revisions due today for a person"""
    today = datetime.now().date()
    todays_revisions = []
    
    for lecture_id, lecture in data["lectures"].items():
        for stage, date_str in lecture["revision_dates"].items():
            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Check if this revision is due today
            grade_key = f"{lecture_id}_{stage}"
            grade = data["persons"][person]["grades"].get(grade_key)
            
            if not grade and revision_date == today:
                todays_revisions.append({
                    "lecture_id": lecture_id,
                    "lecture_name": lecture["name"],
                    "stage": stage,
                    "date": format_date_for_display(date_str),
                    "difficulty": lecture["difficulty"],
                    "category": lecture["category"]
                })
    
    # Add emergency revisions due today
    for emergency_id, emergency in data["persons"][person].get("emergency_revisions", {}).items():
        emergency_date = datetime.strptime(emergency["date"], "%Y-%m-%d").date()
        if not emergency.get("completed") and emergency_date == today:
            todays_revisions.append({
                "lecture_id": emergency["lecture_id"],
                "lecture_name": emergency["lecture_name"],
                "stage": "EMERGENCY",
                "date": format_date_for_display(emergency["date"]),
                "difficulty": emergency.get("difficulty", 3),
                "category": emergency.get("category", ""),
                "emergency_id": emergency_id
            })
    
    return todays_revisions


def get_missed_revisions(data, person):
    """Get all missed revisions (date < today with no grade)"""
    today = datetime.now().date()
    missed_revisions = []
    
    for lecture_id, lecture in data["lectures"].items():
        for stage, date_str in lecture["revision_dates"].items():
            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            grade_key = f"{lecture_id}_{stage}"
            grade = data["persons"][person]["grades"].get(grade_key)
            
            if not grade and revision_date < today:
                overdue_days = (today - revision_date).days
                missed_revisions.append({
                    "lecture_id": lecture_id,
                    "lecture_name": lecture["name"],
                    "stage": stage,
                    "date": format_date_for_display(date_str),
                    "overdue_days": overdue_days,
                    "difficulty": lecture["difficulty"],
                    "category": lecture["category"]
                })
    
    # Sort by stage first (EMERGENCY, R1-R7), then by overdue days
    stage_order = {"EMERGENCY": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5, "R6": 6, "R7": 7}
    missed_revisions.sort(key=lambda x: (stage_order.get(x["stage"], 9), -x["overdue_days"]))
    return missed_revisions


def _revision_load(difficulty):
    if difficulty <= 2:
        return 1
    if difficulty == 3:
        return 2
    return 3


def _get_revision_date_str(data, person, rev):
    if rev.get("stage") == "EMERGENCY":
        emergency_id = rev.get("emergency_id")
        if emergency_id:
            emergency = data["persons"][person].get("emergency_revisions", {}).get(emergency_id)
            if emergency:
                return emergency.get("date")
        return None
    lecture = data["lectures"].get(rev.get("lecture_id"), {})
    return lecture.get("revision_dates", {}).get(rev.get("stage"))


def _collect_pending_revisions_window(data, person, start_date, end_date):
    pending = []

    for lecture_id, lecture in data["lectures"].items():
        for stage, date_str in lecture["revision_dates"].items():
            revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if revision_date < start_date or revision_date > end_date:
                continue
            grade_key = f"{lecture_id}_{stage}"
            grade = data["persons"][person]["grades"].get(grade_key)
            if grade:
                continue
            pending.append({
                "lecture_id": lecture_id,
                "lecture_name": lecture["name"],
                "stage": stage,
                "date": format_date_for_display(date_str),
                "difficulty": lecture["difficulty"],
                "category": lecture["category"],
                "date_str": date_str,
                "moved_by_dlb": False
            })

    for emergency_id, emergency in data["persons"][person].get("emergency_revisions", {}).items():
        if emergency.get("completed"):
            continue
        emergency_date = datetime.strptime(emergency["date"], "%Y-%m-%d").date()
        if emergency_date < start_date or emergency_date > end_date:
            continue
        pending.append({
            "lecture_id": emergency["lecture_id"],
            "lecture_name": emergency["lecture_name"],
            "stage": "EMERGENCY",
            "date": format_date_for_display(emergency["date"]),
            "difficulty": emergency.get("difficulty", 3),
            "category": emergency.get("category", ""),
            "emergency_id": emergency_id,
            "date_str": emergency["date"],
            "moved_by_dlb": False
        })

    return pending


def apply_daily_load_balancing(data, person, todays_revisions):
    """Post-process today's revisions to smooth daily load without altering schedules."""
    today = datetime.now().date()

    adjusted = []
    for rev in todays_revisions:
        date_str = _get_revision_date_str(data, person, rev)
        rev_copy = dict(rev)
        rev_copy["date_str"] = date_str
        rev_copy["moved_by_dlb"] = False
        adjusted.append(rev_copy)

    def load_of_list(items):
        return sum(_revision_load(item.get("difficulty", 3)) for item in items)

    def days_to_exam(date_str):
        if not date_str or not data.get("exam_date"):
            return 0
        exam_date = datetime.strptime(data["exam_date"], "%Y-%m-%d").date()
        revision_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (exam_date - revision_date).days

    # D5 — High Difficulty Spread
    high_diff = [r for r in adjusted if r.get("difficulty", 3) >= 4 and not r.get("moved_by_dlb")]
    if len(high_diff) > 2:
        high_diff.sort(key=lambda r: (
            r.get("difficulty", 3),
            -days_to_exam(r.get("date_str")),
            r.get("lecture_name", "")
        ))
        extras = high_diff[2:]
        for extra in extras:
            extra["moved_by_dlb"] = True
            adjusted.remove(extra)

    # D4 — Overload Smoothing
    missed_exists = len(get_missed_revisions(data, person)) > 0
    target_threshold = 9 if missed_exists else 7

    def push_candidate(items):
        candidates = [
            r for r in items
            if not r.get("moved_by_dlb") and r.get("stage") != "EMERGENCY"
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda r: (
            r.get("difficulty", 3),
            -days_to_exam(r.get("date_str")),
            r.get("lecture_name", "")
        ))
        return candidates[0]

    while load_of_list(adjusted) > target_threshold:
        candidate = push_candidate(adjusted)
        if not candidate:
            break
        candidate["moved_by_dlb"] = True
        adjusted.remove(candidate)

    # D3 — No-Zero Rule
    if load_of_list(adjusted) == 0:
        window_start = today + timedelta(days=1)
        window_end = today + timedelta(days=3)
        future_pending = _collect_pending_revisions_window(data, person, window_start, window_end)

        if future_pending:
            non_hard = [r for r in future_pending if r.get("difficulty", 3) < 5]
            candidates = non_hard if non_hard else future_pending
            candidates.sort(key=lambda r: (
                datetime.strptime(r["date_str"], "%Y-%m-%d").date(),
                r.get("difficulty", 3),
                r.get("lecture_name", "")
            ))
            pulled = candidates[0]
            pulled["moved_by_dlb"] = True
            pulled["date"] = format_date_for_display(format_date_for_storage(today))
            pulled["date_str"] = format_date_for_storage(today)
            adjusted.append(pulled)

    return adjusted


def calculate_risk_score(data, person, lecture_id):
    """Calculate risk score based on grading history"""
    risk = 0
    grades = data["persons"][person]["grades"]
    
    for stage in REVISION_RATIOS.keys():
        grade_key = f"{lecture_id}_{stage}"
        grade = grades.get(grade_key)
        
        if grade == "FAIL":
            risk += 3
        elif grade == "SKIP":
            risk += 2  # SKIP is soft failure
        elif grade == "PARTIAL":
            risk += 0.5
        elif grade == "PERFECT":
            risk -= 1
    
    return max(0, risk)  # Risk cannot be negative


def check_emergency_revision_needed(data, person, lecture_id):
    """Check if emergency revision should be injected"""
    grades = data["persons"][person]["grades"]
    lecture = data["lectures"][lecture_id]
    
    # Count recent failures/skips
    fail_count = 0
    skip_count = 0
    
    for stage in REVISION_RATIOS.keys():
        grade_key = f"{lecture_id}_{stage}"
        grade = grades.get(grade_key)
        
        if grade == "FAIL":
            fail_count += 1
        elif grade == "SKIP":
            skip_count += 1
    
    # Inject emergency if 2+ FAILs or 2+ SKIPs
    if fail_count >= 2 or skip_count >= 2:
        # Create emergency revision for tomorrow
        tomorrow = format_date_for_storage(datetime.now() + timedelta(days=1))
        emergency_id = f"{lecture_id}_emergency_{datetime.now().timestamp()}"
        
        data["persons"][person]["emergency_revisions"][emergency_id] = {
            "lecture_id": lecture_id,
            "lecture_name": lecture["name"],
            "date": tomorrow,
            "difficulty": lecture["difficulty"],
            "category": lecture["category"],
            "completed": False,
            "reason": f"Repeated failures (FAIL: {fail_count}, SKIP: {skip_count})"
        }
        
        save_data(data)
        return True
    
    return False


def grade_revision(data, person, lecture_id, stage, grade, is_emergency=False, emergency_id=None):
    """Grade a revision for a person"""
    if is_emergency:
        data["persons"][person]["emergency_revisions"][emergency_id]["completed"] = True
        data["persons"][person]["emergency_revisions"][emergency_id]["grade"] = grade
    else:
        grade_key = f"{lecture_id}_{stage}"
        data["persons"][person]["grades"][grade_key] = grade
    
    save_data(data)
    
    # Check if emergency revision is needed after grading
    if grade in ["FAIL", "SKIP"]:
        check_emergency_revision_needed(data, person, lecture_id)


def reflow_revisions(data, lecture_id):
    """Reflow revisions for a lecture (affects both persons)"""
    lecture = data["lectures"][lecture_id]
    
    if not data["exam_date"]:
        return
    
    new_dates = calculate_revision_dates(
        lecture["study_date"],
        data["exam_date"],
        lecture["difficulty"]
    )
    
    lecture["revision_dates"] = new_dates
    save_data(data)


# =======================
# VIEW: Home / Today
# =======================
def view_home():
    st.title("🏠 Today's Revisions")
    
    data = load_data()
    
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
    
    # Today's revisions
    todays = get_todays_revisions(data, st.session_state.current_person)
    todays = apply_daily_load_balancing(data, st.session_state.current_person, todays)
    
    # Sort by stage: EMERGENCY first, then R1, R2, R3, R4, R5, R6, R7
    stage_order = {"EMERGENCY": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5, "R6": 6, "R7": 7}
    todays.sort(key=lambda x: stage_order.get(x["stage"], 9))
    
    if todays:
        st.write(f"**{len(todays)} revision(s) due today:**")
        
        for idx, rev in enumerate(todays):
            with st.container():
                st.markdown(f"### {rev['lecture_name']}")
                col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
                
                with col1:
                    st.write(f"**Stage:** {rev['stage']}")
                    st.write(f"**Category:** {rev['category']}")
                    st.write(f"**Difficulty:** {rev['difficulty']}/5")
                
                is_emergency = rev["stage"] == "EMERGENCY"
                emergency_id = rev.get("emergency_id")
                
                with col2:
                    if st.button("❌ FAIL", key=f"fail_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person, 
                                     rev['lecture_id'], rev['stage'], "FAIL",
                                     is_emergency, emergency_id)
                        st.rerun()
                
                with col3:
                    if st.button("⚠️ PARTIAL", key=f"partial_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person,
                                     rev['lecture_id'], rev['stage'], "PARTIAL",
                                     is_emergency, emergency_id)
                        st.rerun()
                
                with col4:
                    if st.button("✅ PERFECT", key=f"perfect_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person,
                                     rev['lecture_id'], rev['stage'], "PERFECT",
                                     is_emergency, emergency_id)
                        st.rerun()
                
                with col5:
                    if st.button("⏭️ SKIP", key=f"skip_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person,
                                     rev['lecture_id'], rev['stage'], "SKIP",
                                     is_emergency, emergency_id)
                        st.rerun()
                
                st.divider()
    else:
        st.info("🎉 No revisions due today! Well done!")
    
    # Missed revisions
    missed = get_missed_revisions(data, st.session_state.current_person)
    
    if missed:
        st.warning(f"⚠️ **{len(missed)} missed revision(s):**")
        
        for idx, rev in enumerate(missed):
            with st.expander(f"{rev['lecture_name']} - {rev['stage']} ({rev['overdue_days']} days overdue)"):
                col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
                
                with col1:
                    st.write(f"**Due Date:** {rev['date']}")
                    st.write(f"**Category:** {rev['category']}")
                
                with col2:
                    if st.button("❌ FAIL", key=f"missed_fail_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person,
                                     rev['lecture_id'], rev['stage'], "FAIL")
                        st.rerun()
                
                with col3:
                    if st.button("⚠️ PARTIAL", key=f"missed_partial_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person,
                                     rev['lecture_id'], rev['stage'], "PARTIAL")
                        st.rerun()
                
                with col4:
                    if st.button("✅ PERFECT", key=f"missed_perfect_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person,
                                     rev['lecture_id'], rev['stage'], "PERFECT")
                        st.rerun()
                
                with col5:
                    if st.button("⏭️ SKIP", key=f"missed_skip_{idx}", use_container_width=True):
                        grade_revision(data, st.session_state.current_person,
                                     rev['lecture_id'], rev['stage'], "SKIP")
                        st.rerun()


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
                    "revision_dates": revision_dates
                }
                
                save_data(data)
                st.success(f"✅ Lecture '{lecture_name}' added for both Harsh and Divya!")
                st.info(f"📅 Generated {len(revision_dates)} revision stages: {', '.join(revision_dates.keys())}")


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
        category = lecture["category"]
        if category not in lectures_by_category:
            lectures_by_category[category] = []
        lectures_by_category[category].append((lecture_id, lecture))
    
    # Create tabs for each category
    categories_present = sorted(lectures_by_category.keys())
    
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
                                edit_category = st.selectbox("Category", CATEGORIES, 
                                                            index=CATEGORIES.index(lecture["category"]),
                                                            key=f"cat_{lecture_id}")
                            
                            with col3:
                                risk = calculate_risk_score(data, st.session_state.current_person, lecture_id)
                                st.metric("Risk Score", risk)
                                
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
                                            button_label = f"{stage}\n{format_date_compact(date_str)}\n✓ {grade}"
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


# =======================
# MAIN APP
# =======================
def main():
    # Sidebar navigation - force sidebar rendering
    with st.sidebar:
        st.title("📚 SSC GK Tracker")
        
        view = st.radio(
            "Navigation",
            ["🏠 Home / Today", "➕ Add Lecture", "📋 Full Revision Plan"],
            key="navigation"
        )
        
        st.divider()
        st.caption("Built with ❤️ for SSC GK preparation")
    
    if view == "🏠 Home / Today":
        view_home()
    elif view == "➕ Add Lecture":
        view_add_lecture()
    elif view == "📋 Full Revision Plan":
        view_revision_plan()


if __name__ == "__main__":
    main()