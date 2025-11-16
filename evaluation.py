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
    if firebase_admin._apps:
        return firestore.client()

    cfg = None
    try:
        if "firebase" in st.secrets:
            cfg = dict(st.secrets["firebase"])
        else:
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
# LOAD QUESTION BANKS
# ------------------------------------------------------------
QUESTION_FILES = {
    "Aptitude Test": "aptitude.csv",
    "Adaptability & Learning": "adaptability_learning.csv",
    "Communication Skills - Objective": "communication_skills_objective.csv",
    "Communication Skills - Descriptive": "communication_skills_descriptive.csv",
}


@st.cache_data
def load_question_banks():
    banks = {}
    for section, filename in QUESTION_FILES.items():
        try:
            df = pd.read_csv(filename)
            df.columns = [str(c).strip() for c in df.columns]
            if "Type" in df.columns:
                df["Type"] = df["Type"].astype(str).str.lower()
            banks[section] = df
        except:
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
# STUDENT MAP
# ------------------------------------------------------------
@st.cache_data
def load_student_map():
    student_map = {}
    docs = db.collection("student_responses").stream()

    for snap in docs:
        data = snap.to_dict() or {}
        roll = data.get("Roll")
        section = data.get("Section")

        if not roll or not section:
            continue

        if roll not in student_map:
            student_map[roll] = {"docs": [], "evaluated": False}

        student_map[roll]["docs"].append((section, snap.id))

    return student_map


student_map = load_student_map()
if not student_map:
    st.stop()


# ------------------------------------------------------------
# SELECT ROLL
# ------------------------------------------------------------
rolls_sorted = sorted(student_map.keys())

selected_roll = st.selectbox("Select Student Roll Number", rolls_sorted)

docs_for_student = student_map[selected_roll]["docs"]

# Preload document data
doc_data_map = {}
for section, doc_id in docs_for_student:
    snap = db.collection("student_responses").document(doc_id).get()
    doc_data_map[doc_id] = snap.to_dict() or {}


# ------------------------------------------------------------
# MANUAL TESTS AVAILABLE
# ------------------------------------------------------------
manual_meta = {}
for section, doc_id in docs_for_student:
    if section in MANUAL_TESTS:
        manual_meta[section] = {"doc_id": doc_id}

tests_available = [t for t in MANUAL_TESTS if t in manual_meta]

selected_test = st.selectbox("Select Test for Manual Evaluation", tests_available)

selected_doc_id = manual_meta[selected_test]["doc_id"]
selected_doc_data = doc_data_map[selected_doc_id]
selected_responses = selected_doc_data.get("Responses") or []
selected_eval = selected_doc_data.get("Evaluation") or {}
saved_text_marks = {str(k): int(v) for k, v in (selected_eval.get("text_marks") or {}).items()}

df_selected = question_banks[selected_test]


# ------------------------------------------------------------
# TEXT SCORING (DESCRIPTIVE)
# ------------------------------------------------------------
from functools import lru_cache

FOUR = {12, 13, 14, 16, 17, 18}
THREE = {22, 23, 24, 25, 28, 29, 30, 34}


def parse_qid(q):
    s = str(q)
    if s.startswith("Q"): s = s[1:]
    try: return int(s)
    except: return -1


def scale_for(qid):
    q = parse_qid(qid)
    if q in FOUR: return [0, 1, 2, 3]
    if q in THREE: return [0, 1, 2]
    return [0, 1]


short_df = df_selected[df_selected["Type"] == "short"]

marks_given = {}
text_total_current = 0

for _, row in short_df.iterrows():
    qid = str(row["QuestionID"])
    qtext = row["Question"]

    answer = "(no answer)"
    for r in selected_responses:
        if str(r["QuestionID"]) == qid:
            answer = str(r.get("Response", "(no answer)"))

    scale = scale_for(qid)
    default = saved_text_marks.get(qid, 0)
    if default not in scale:
        default = 0

    with st.expander(f"Q{qid}: {qtext}", expanded=True):
        st.write(f"**Answer:** {answer}")
        mark = st.radio(
            "Marks:",
            scale,
            index=scale.index(default),
            key=f"mark_{selected_roll}_{selected_test}_{qid}",
            horizontal=True
        )

    marks_given[qid] = mark
    text_total_current += mark


st.markdown("---")


# ------------------------------------------------------------
# AUTO SCORES
# ------------------------------------------------------------
def calc_mcq(df, responses):
    if df.empty: return 0
    total = 0
    for r in responses:
        qid = str(r["QuestionID"])
        ans = str(r["Response"]).strip()

        match = df[df["QuestionID"].astype(str) == qid]
        if match.empty: continue
        row = match.iloc[0]
        if row["Type"] != "mcq": continue

        correct = str(row.get("Answer", "")).strip()
        if ans == correct:
            total += 1
    return total


def calc_likert(df, responses):
    if df.empty:
        return 0

    total = 0
    for r in responses:
        resp_raw = r.get("Response", 0)

        # --- SAFELY HANDLE ALL BAD DATA ---
        try:
            resp_str = str(resp_raw).strip()
            val = int(resp_str)
        except:
            val = 0   # fallback when invalid

        score = max(0, min(4, val - 1))  # map Likert 1–5 → 0–4

        qid = str(r.get("QuestionID", ""))
        match = df[df["QuestionID"].astype(str) == qid]

        if not match.empty and match.iloc[0]["Type"] == "likert":
            total += score

    return total


def total_auto_scores():
    mcq = 0
    likert = 0
    for section, doc_id in docs_for_student:
        df = question_banks.get(section, pd.DataFrame())
        data = doc_data_map[doc_id]
        resp = data.get("Responses") or []

        mcq += calc_mcq(df, resp)
        likert += calc_likert(df, resp)

    return mcq, likert


mcq_all, likert_all = total_auto_scores()

# GRAND TOTAL
grand_total = mcq_all + likert_all + text_total_current

st.write(f"**MCQ Score (Auto, all tests):** {mcq_all}")
st.write(f"**Likert Score (Auto, all tests):** {likert_all}")
st.write(f"**Text Score (This test):** {text_total_current}")
st.subheader(f"GRAND TOTAL (All Tests) = {grand_total}")


# ------------------------------------------------------------
# SAVE EVALUATION  (FINAL, FIXED, WORKING)
# ------------------------------------------------------------
# ------------------------------------------------------------
# SAVE EVALUATION (FIXED & COMPLETE)
# ------------------------------------------------------------
if st.button("💾 Save Evaluation"):

    # text_marks collected from UI
    text_marks_dict = {qid: mark for qid, mark in marks_given.items()}

    if not text_marks_dict:
        st.error("No descriptive marks found! Expand questions and enter marks.")
        st.stop()

    # Load auto-evaluated scores for THIS test
    df_this = question_banks[selected_test]
    auto_mcq = 0
    auto_likert = 0

    for r in selected_responses:
        qid = str(r.get("QuestionID", ""))

        row_match = df_this[df_this["QuestionID"].astype(str) == qid]
        if row_match.empty:
            continue

        row = row_match.iloc[0]
        qtype = str(row.get("Type", "")).lower()

        # MCQ
        if qtype == "mcq":
            correct = str(row.get("Answer", "")).strip()
            if str(r.get("Response", "")).strip() == correct:
                auto_mcq += 1

        # LIKERT
        elif qtype == "likert":
            try:
                val = int(r.get("Response", 0))
                auto_likert += max(0, min(4, val - 1))
            except:
                pass

    # Descriptive total for this test
    text_total = sum(text_marks_dict.values())

    # Final per-test score
    final_total = auto_mcq + auto_likert + text_total

    # Compute NEW GRAND TOTAL (all tests)
    doc_scores, mcq_all, likert_all = compute_auto_scores_for_roll(docs_for_student)

    # sum saved text scores from other tests
    saved_text = 0
    for section, doc_id in docs_for_student:
        if section != selected_test:
            data = doc_data_map[doc_id]
            eval_prev = data.get("Evaluation", {})
            saved_text += int(eval_prev.get("text_total", 0))

    grand_total = mcq_all + likert_all + saved_text + text_total

    # Save into Firestore
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

