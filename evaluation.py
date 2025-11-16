import json
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

import firebase_admin
from firebase_admin import credentials, firestore


# ------------------------------------------------------------
# STREAMLIT PAGE CONFIG
# ------------------------------------------------------------
st.set_page_config(page_title="Faculty Evaluation Dashboard", layout="wide")
st.title("👩‍🏫 Faculty Evaluation Dashboard")


# ------------------------------------------------------------
# FIREBASE INIT
# ------------------------------------------------------------
@st.cache_resource
def init_firebase():
    """Initialise Firestore using st.secrets['firebase'] or firebase_key.json."""
    if firebase_admin._apps:
        return firestore.client()

    cfg = None
    try:
        if "firebase" in st.secrets:
            # st.secrets["firebase"] is a mapping with the service account JSON
            cfg = dict(st.secrets["firebase"])
        else:
            # Fallback for local runs
            with open("firebase_key.json", "r") as f:
                cfg = json.load(f)
    except Exception as e:
        st.error(f"Firebase credentials not found: {e}")
        return None

    try:
        cred = credentials.Certificate(cfg)
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"Failed to initialise Firebase: {e}")
        return None


db = init_firebase()
if db is None:
    st.stop()


# ------------------------------------------------------------
# LOAD QUESTION BANKS (CSV)
# ------------------------------------------------------------
QUESTION_FILES = {
    "Aptitude Test": "aptitude.csv",
    "Adaptability & Learning": "adaptability_learning.csv",
    "Communication Skills - Objective": "communication_skills_objective.csv",
    "Communication Skills - Descriptive": "communication_skills_descriptive.csv",
}


@st.cache_data
def load_question_banks() -> Dict[str, pd.DataFrame]:
    banks = {}
    for section, filename in QUESTION_FILES.items():
        try:
            df = pd.read_csv(filename)
            # normalise column names a bit
            df.columns = [str(c).strip() for c in df.columns]
            if "Type" in df.columns:
                df["Type"] = df["Type"].astype(str).str.strip().str.lower()
            banks[section] = df
        except Exception as e:
            st.error(f"Error loading {filename}: {e}")
            banks[section] = pd.DataFrame()
    return banks


question_banks = load_question_banks()

AUTO_TESTS = [
    "Adaptability & Learning",
    "Communication Skills - Objective",
]

MANUAL_TESTS = [
    "Aptitude Test",
    "Communication Skills - Descriptive",
]


# ------------------------------------------------------------
# FIRESTORE → STUDENT MAP
# roll -> { 'docs': [(section, doc_id)], 'evaluated': bool }
# evaluated = any doc has Evaluation.grand_total
# ------------------------------------------------------------
@st.cache_data
def load_student_map() -> Dict[str, Dict]:
    student_map: Dict[str, Dict] = {}
    try:
        docs = db.collection("student_responses").stream()
    except Exception as e:
        st.error(f"Error reading Firestore: {e}")
        return {}

    for snap in docs:
        data = snap.to_dict() or {}
        roll = data.get("Roll") or data.get("roll")
        section = data.get("Section")
        if not roll or not section:
            continue

        if roll not in student_map:
            student_map[roll] = {"docs": [], "evaluated": False}

        student_map[roll]["docs"].append((section, snap.id))

        eval_block = data.get("Evaluation") or {}
        if isinstance(eval_block, dict) and eval_block.get("grand_total") is not None:
            student_map[roll]["evaluated"] = True

    return student_map


student_map = load_student_map()

if not student_map:
    st.info("No student responses found in Firestore.")
    st.stop()


# ------------------------------------------------------------
# HELPER FUNCTIONS
# ------------------------------------------------------------
FOUR_MARK_QIDS = {12, 13, 14, 16, 17, 18}
THREE_MARK_QIDS = {22, 23, 24, 25, 28, 29, 30, 34}


def parse_int_qid(qid_val) -> int:
    """Convert QuestionID value to an int if possible."""
    s = str(qid_val).strip()
    if s.lower().startswith("q"):
        s = s[1:]
    try:
        return int(s)
    except Exception:
        return -1


def get_text_scale(qid_val: str) -> List[int]:
    """Return the marking scale for a given QuestionID string."""
    qid_int = parse_int_qid(qid_val)
    if qid_int in FOUR_MARK_QIDS:
        return [0, 1, 2, 3]
    if qid_int in THREE_MARK_QIDS:
        return [0, 1, 2]
    return [0, 1]


def get_correct_answer(row: pd.Series):
    """Try to fetch the correct answer from any reasonable column name."""
    for col in ["Answer", "Correct", "CorrectAnswer", "Ans", "AnswerKey", "RightAnswer"]:
        if col in row and pd.notna(row[col]):
            return str(row[col]).strip()
    return None


def calc_mcq(df: pd.DataFrame, responses: List[dict]) -> int:
    """Auto-evaluate MCQ questions for a single test."""
    if df is None or df.empty:
        return 0

    total = 0
    for r in responses:
        qid = str(r.get("QuestionID"))
        ans = str(r.get("Response", "")).strip()

        match = df[df["QuestionID"].astype(str) == qid]
        if match.empty:
            continue
        row = match.iloc[0]
        if str(row.get("Type", "")).lower() != "mcq":
            continue

        correct = get_correct_answer(row)
        if correct is not None and ans == correct:
            total += 1
    return total


def calc_likert(df: pd.DataFrame, responses: List[dict]) -> int:
    """
    Auto-evaluate likert questions.
    Mapping: response 1..5 -> 0..4 (linear).
    """
    if df is None or df.empty:
        return 0

    total = 0
    for r in responses:
        qid = str(r.get("QuestionID"))
        try:
            val = int(r.get("Response", 0))
        except Exception:
            continue

        match = df[df["QuestionID"].astype(str) == qid]
        if match.empty:
            continue
        row = match.iloc[0]
        if str(row.get("Type", "")).lower() != "likert":
            continue

        score = max(0, min(4, val - 1))  # 1→0, 2→1, 3→2, 4→3, 5→4
        total += score
    return total


def compute_auto_scores_for_roll(
    docs_for_roll: List[Tuple[str, str]]
) -> Tuple[Dict[str, dict], int, int]:
    """
    For each document (section, doc_id) of the student:
    - compute mcq and likert scores
    Returns:
        doc_scores: doc_id -> {"mcq": x, "likert": y}
        mcq_sum_all, likert_sum_all
    """
    doc_scores: Dict[str, dict] = {}
    mcq_sum = 0
    likert_sum = 0

    for section, doc_id in docs_for_roll:
        df = question_banks.get(section)
        try:
            snap = db.collection("student_responses").document(doc_id).get()
            data = snap.to_dict() or {}
        except Exception:
            data = {}

        responses = data.get("Responses") or []

        mcq_total = calc_mcq(df, responses)
        likert_total = calc_likert(df, responses)

        doc_scores[doc_id] = {"mcq": mcq_total, "likert": likert_total}
        mcq_sum += mcq_total
        likert_sum += likert_total

    return doc_scores, mcq_sum, likert_sum


# ------------------------------------------------------------
# UI: SELECT STUDENT
# ------------------------------------------------------------
rolls_sorted = sorted(student_map.keys())


def format_roll(r: str) -> str:
    flag = " ✓" if student_map[r]["evaluated"] else ""
    return f"{r}{flag}"


selected_roll = st.selectbox(
    "Select Student Roll Number",
    rolls_sorted,
    format_func=format_roll,
)

docs_for_student = student_map[selected_roll]["docs"]

if not docs_for_student:
    st.warning("No test documents found for this student.")
    st.stop()

# Pre-fetch document data for this student (once)
doc_data_map: Dict[str, dict] = {}
for section, doc_id in docs_for_student:
    snap = db.collection("student_responses").document(doc_id).get()
    doc_data_map[doc_id] = snap.to_dict() or {}


# ------------------------------------------------------------
# DETERMINE MANUAL TESTS AVAILABLE FOR THIS STUDENT
# ------------------------------------------------------------
manual_meta: Dict[str, dict] = {}  # section -> {"doc_id": ..., "text_done": bool}

for section, doc_id in docs_for_student:
    if section not in MANUAL_TESTS:
        continue
    data = doc_data_map.get(doc_id, {})
    eval_block = data.get("Evaluation") or {}
    text_marks = eval_block.get("text_marks") or {}
    text_total_saved = eval_block.get("text_total", 0)
    text_done = bool(text_marks) or (text_total_saved not in (None, 0))
    manual_meta[section] = {"doc_id": doc_id, "text_done": text_done}

if not manual_meta:
    st.info("This student only has auto-evaluated tests (no manual text marking).")
    # still compute and show auto scores + grand total
    doc_scores, mcq_all, likert_all = compute_auto_scores_for_roll(docs_for_student)
    grand_total = mcq_all + likert_all
    st.subheader(f"GRAND TOTAL (All Tests) = {grand_total}")
    st.stop()

# Keep tests in a fixed order
tests_available = [t for t in MANUAL_TESTS if t in manual_meta]


def format_test(t: str) -> str:
    meta = manual_meta[t]
    return f"{t}{' ✓' if meta['text_done'] else ''}"


selected_test = st.selectbox(
    "Select Test for Manual Evaluation",
    tests_available,
    format_func=format_test,
)

selected_doc_id = manual_meta[selected_test]["doc_id"]
selected_doc_data = doc_data_map[selected_doc_id]
selected_responses = selected_doc_data.get("Responses") or []
selected_eval = selected_doc_data.get("Evaluation") or {}
saved_text_marks: Dict[str, int] = {
    str(k): int(v) for k, v in (selected_eval.get("text_marks") or {}).items()
}

df_selected = question_banks.get(selected_test, pd.DataFrame())
if df_selected is None or df_selected.empty:
    st.error(f"No questions loaded for section '{selected_test}'.")
    st.stop()

# ------------------------------------------------------------
# BUILD TEXT MARKING UI (SHORT QUESTIONS)
# ------------------------------------------------------------
short_df = df_selected[df_selected["Type"] == "short"]

marks_given: Dict[str, int] = {}
text_total_current = 0

for _, row in short_df.iterrows():
    qid_val = row["QuestionID"]
    qid_str = str(qid_val)
    qtext = str(row["Question"])

    # find student's answer
    student_answer = "(no answer)"
    for r in selected_responses:
        if str(r.get("QuestionID")) == qid_str:
            student_answer = str(r.get("Response", "(no answer)"))
            break

    scale = get_text_scale(qid_str)

    # default mark = previously saved (if any), else 0
    default_mark = saved_text_marks.get(qid_str, 0)
    if default_mark not in scale:
        default_mark = 0
    try:
        default_index = scale.index(default_mark)
    except ValueError:
        default_index = 0

    with st.expander(f"Q{qid_str}: {qtext}", expanded=True):
        col_q, col_m = st.columns([3, 1])
        with col_q:
            st.markdown(f"**Student Answer:** {student_answer}")
        with col_m:
            mark = st.radio(
                "Marks:",
                scale,
                index=default_index,
                horizontal=True,
                key=f"mark_{selected_roll}_{selected_test}_{qid_str}",
            )

    marks_given[qid_str] = int(mark)
    text_total_current += int(mark)

st.markdown("---")

# ------------------------------------------------------------
# AUTO SCORES + GRAND TOTAL (ALL TESTS)
# ------------------------------------------------------------
doc_scores, mcq_all, likert_all = compute_auto_scores_for_roll(docs_for_student)

grand_total = 0
for section, doc_id in docs_for_student:
    auto_mcq = doc_scores[doc_id]["mcq"]
    auto_likert = doc_scores[doc_id]["likert"]

    if section == selected_test:
        text_total = text_total_current
    else:
        data = doc_data_map.get(doc_id, {})
        eval_block = data.get("Evaluation") or {}
        text_total = int(eval_block.get("text_total", 0) or 0)

    final_total = auto_mcq + auto_likert + text_total
    grand_total += final_total

st.write(f"**MCQ Score (Auto, all tests)**: {mcq_all}")
st.write(f"**Likert Score (Auto, all tests)**: {likert_all}")
st.write(f"**Text Marks (This Test)**: {text_total_current}")
st.subheader(f"GRAND TOTAL (All Tests) = {grand_total}")

# ------------------------------------------------------------
# SAVE EVALUATION
# ------------------------------------------------------------
if st.button("💾 Save Evaluation"):
    # Save evaluation for the selected test document
    this_auto_mcq = doc_scores[selected_doc_id]["mcq"]
    this_auto_likert = doc_scores[selected_doc_id]["likert"]
    this_final = this_auto_mcq + this_auto_likert + text_total_current

    db.collection("student_responses").document(selected_doc_id).set(
        {
            "Evaluation": {
                "text_marks": marks_given,
                "text_total": text_total_current,
                "mcq_total": this_auto_mcq,
                "likert_total": this_auto_likert,
                "final_total": this_final,
                "grand_total": grand_total,
            }
        },
        merge=True,
    )

    # Also propagate grand_total to the other test documents for this roll
    for section, doc_id in docs_for_student:
        if doc_id == selected_doc_id:
            continue
        db.collection("student_responses").document(doc_id).set(
            {"Evaluation": {"grand_total": grand_total}},
            merge=True,
        )

    st.success("Evaluation saved successfully ✅")
    st.experimental_rerun()
