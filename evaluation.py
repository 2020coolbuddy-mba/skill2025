import json
from typing import Dict, List, Tuple
import pandas as pd
import streamlit as st

import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
#  STREAMLIT CONFIG
# ============================================================
st.set_page_config(page_title="Faculty Evaluation Dashboard", layout="wide")
st.title("👩‍🏫 Faculty Evaluation Dashboard")


# ============================================================
#  FIREBASE INITIALIZATION
# ============================================================
@st.cache_resource
def init_firebase():
    if firebase_admin._apps:
        return firestore.client()

    try:
        if "firebase" in st.secrets:
            cfg = dict(st.secrets["firebase"])
        else:
            with open("firebase_key.json", "r") as f:
                cfg = json.load(f)

        cred = credentials.Certificate(cfg)
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"Firebase Init Failed: {e}")
        return None


db = init_firebase()
if not db:
    st.stop()


# ============================================================
#  FILE NAMES FOR CSV QUESTION BANKS
# ============================================================
QUESTION_FILES = {
    "Aptitude_Test": "aptitude.csv",
    "Adaptability_&_Learning": "adaptability_learning.csv",
    "Communication_Skills_-_Objective": "communication_skills_objective.csv",
    "Communication_Skills_-_Descriptive": "communication_skills_descriptive.csv",
}

# Human-readable names for display
DISPLAY_NAME = {
    "Aptitude_Test": "Aptitude Test",
    "Adaptability_&_Learning": "Adaptability & Learning",
    "Communication_Skills_-_Objective": "Communication Skills - Objective",
    "Communication_Skills_-_Descriptive": "Communication Skills - Descriptive",
}


# ============================================================
#  LOAD QUESTION BANKS
# ============================================================
@st.cache_data
def load_question_banks():
    banks = {}
    for section, filename in QUESTION_FILES.items():
        try:
            df = pd.read_csv(filename)
            df.columns = [c.strip() for c in df.columns]
            if "Type" in df.columns:
                df["Type"] = df["Type"].astype(str).str.lower()
            banks[section] = df
        except Exception as e:
            st.error(f"Could not load {filename}: {e}")
            banks[section] = pd.DataFrame()
    return banks


question_banks = load_question_banks()


# ============================================================
#  LOAD STUDENTS FROM FIRESTORE
# ============================================================
@st.cache_data
def load_student_map():
    student_map = {}
    docs = db.collection("student_responses").stream()

    for snap in docs:
        data = snap.to_dict() or {}
        roll = data.get("Roll")
        section = data.get("Section")   # EXACT Firestore section

        if not roll or not section:
            continue

        if roll not in student_map:
            student_map[roll] = {"docs": []}

        student_map[roll]["docs"].append((section, snap.id))

    return student_map


student_map = load_student_map()
if not student_map:
    st.warning("No student responses found.")
    st.stop()


# ============================================================
#  SELECT STUDENT
# ============================================================
rolls_sorted = sorted(student_map.keys())
selected_roll = st.selectbox("Select Student Roll Number", rolls_sorted)

docs_for_student = student_map[selected_roll]["docs"]

# Preload Firestore data
doc_data_map = {}
for section, doc_id in docs_for_student:
    snap = db.collection("student_responses").document(doc_id).get()
    doc_data_map[doc_id] = snap.to_dict() or {}


# ============================================================
#  SCORE CALCULATION FUNCTIONS
# ============================================================
def calc_mcq(df, responses):
    if df.empty:
        return 0

    total = 0
    for r in responses:
        qid = str(r.get("QuestionID"))
        ans = str(r.get("Response", "")).strip()

        match = df[df["QuestionID"].astype(str) == qid]
        if match.empty:
            continue

        row = match.iloc[0]
        if row["Type"] != "mcq":
            continue

        correct = str(row.get("Answer", "")).strip()
        if ans.lower() == correct.lower():
            total += 1

    return total


def calc_likert(df, responses):
    total = 0
    for r in responses:
        qid = str(r.get("QuestionID"))
        resp_raw = r.get("Response", 0)

        try:
            val = int(str(resp_raw).strip())
        except:
            val = 0

        match = df[df["QuestionID"].astype(str) == qid]
        if match.empty:
            continue

        row = match.iloc[0]
        if row["Type"] != "likert":
            continue

        total += max(0, min(4, val - 1))  # map 1–5 to 0–4

    return total


# ============================================================
#  COMPUTE AUTO SCORES FOR ALL TESTS
# ============================================================
def compute_auto_scores_for_roll(docs):
    mcq_sum = 0
    likert_sum = 0
    for section, doc_id in docs:
        df = question_banks.get(section, pd.DataFrame())
        data = doc_data_map[doc_id]
        resp = data.get("Responses") or []

        mcq_sum += calc_mcq(df, resp)
        likert_sum += calc_likert(df, resp)

    return mcq_sum, likert_sum


# ============================================================
#  MANUAL TEST SELECTION
# ============================================================
MANUAL_TESTS = ["Aptitude_Test", "Communication_Skills_-_Descriptive"]

available_manual = [s for s, _ in docs_for_student if s in MANUAL_TESTS]

selected_test = st.selectbox(
    "Select Test for Manual Evaluation",
    available_manual,
    format_func=lambda x: DISPLAY_NAME[x]
)

selected_doc_id = [d for s, d in docs_for_student if s == selected_test][0]
selected_doc = doc_data_map[selected_doc_id]

selected_responses = selected_doc.get("Responses") or []
selected_eval = selected_doc.get("Evaluation") or {}
saved_text_marks = selected_eval.get("text_marks", {})

df_this = question_banks[selected_test]


# ============================================================
#  DESCRIPTIVE MARKING UI
# ============================================================
FOUR = {12, 13, 14, 16, 17, 18}
THREE = {22, 23, 24, 25, 28, 29, 30, 34}

def scale_for(qid):
    try:
        q = int(str(qid).replace("Q", ""))
    except:
        return [0, 1]

    if q in FOUR:
        return [0, 1, 2, 3]
    if q in THREE:
        return [0, 1, 2]
    return [0, 1]


short_df = df_this[df_this["Type"] == "short"]

marks_given = {}
text_total_current = 0

for _, row in short_df.iterrows():
    qid = str(row["QuestionID"])
    qtext = row["Question"]

    # Identify student's answer
    student_answer = "(no answer)"
    for r in selected_responses:
        if str(r.get("QuestionID")) == qid:
            student_answer = str(r.get("Response", "(no answer)"))

    scale = scale_for(qid)
    default = saved_text_marks.get(qid, 0)
    if default not in scale:
        default = 0

    with st.expander(f"Q{qid}: {qtext}", expanded=True):
        st.write(f"**Answer:** {student_answer}")
        mark = st.radio(
            "Marks:",
            scale,
            index=scale.index(default),
            horizontal=True,
            key=f"m_{selected_doc_id}_{qid}"
        )

    marks_given[qid] = mark
    text_total_current += mark


# ============================================================
#  AUTO + MANUAL TOTAL DISPLAY
# ============================================================
mcq_all, likert_all = compute_auto_scores_for_roll(docs_for_student)

grand_total = mcq_all + likert_all + text_total_current

st.write(f"**MCQ Score (Auto):** {mcq_all}")
st.write(f"**Likert Score (Auto):** {likert_all}")
st.write(f"**Text Score (This Test):** {text_total_current}")
st.subheader(f"GRAND TOTAL (All Tests) = {grand_total}")


# ============================================================
#  SAVE EVALUATION
# ============================================================
if st.button("💾 Save Evaluation"):

    text_marks_dict = {qid: int(mark) for qid, mark in marks_given.items()}
    text_total = sum(text_marks_dict.values())

    # Compute MCQ + Likert JUST for this test
    auto_mcq = calc_mcq(df_this, selected_responses)
    auto_likert = calc_likert(df_this, selected_responses)
    final_total = auto_mcq + auto_likert + text_total

    # Compute GRAND TOTAL again
    mcq_all, likert_all = compute_auto_scores_for_roll(docs_for_student)

    saved_text_other = 0
    for sec, did in docs_for_student:
        if sec != selected_test:
            ev = doc_data_map[did].get("Evaluation", {})
            saved_text_other += int(ev.get("text_total", 0))

    grand_total = mcq_all + likert_all + saved_text_other + text_total

    # Save to Firestore
    doc_ref = db.collection("student_responses").document(selected_doc_id)

    new_eval = {
        "mcq_total": auto_mcq,
        "likert_total": auto_likert,
        "text_total": text_total,
        "final_total": final_total,
        "grand_total": grand_total,
        "text_marks": text_marks_dict,
    }

    doc_ref.set({"Evaluation": new_eval}, merge=True)

    st.success("Evaluation saved successfully!")
