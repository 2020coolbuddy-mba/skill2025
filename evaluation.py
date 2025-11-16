import streamlit as st
import pandas as pd
import json
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------------------------------------------
# FIREBASE INIT (SAFE, NO DUPLICATION)
# -------------------------------------------------------
@st.cache_resource
def init_firebase():
    if firebase_admin._apps:
        return firestore.client()
    try:
        cfg = dict(st.secrets["firebase"])
        cred = credentials.Certificate(cfg)
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"Firebase initialization failed: {e}")
        return None


db = init_firebase()
if db is None:
    st.stop()

# -------------------------------------------------------
# LOAD CSV QUESTION BANKS (STATIC, NON-CHANGING)
# -------------------------------------------------------
@st.cache_data
def load_qbanks():
    return {
        "Aptitude Test": pd.read_csv("aptitude.csv"),
        "Adaptability & Learning": pd.read_csv("adaptability_learning.csv"),
        "Communication Skills - Objective": pd.read_csv("communication_skills_objective.csv"),
        "Communication Skills - Descriptive": pd.read_csv("communication_skills_descriptive.csv")
    }


QBANKS = load_qbanks()

AUTO_EVAL = ["Adaptability & Learning", "Communication Skills - Objective"]
MANUAL_EVAL = ["Aptitude Test", "Communication Skills - Descriptive"]

ALL_SECTIONS = list(QBANKS.keys())

# -------------------------------------------------------
# HELPERS
# -------------------------------------------------------
def get_correct_answer(row):
    for col in ["Answer", "CorrectAnswer", "Correct", "Ans", "AnswerKey", "RightAnswer"]:
        if col in row and not pd.isna(row[col]):
            return str(row[col]).strip()
    return None

def calc_mcq(df, responses):
    total = 0
    for r in responses:
        qid = str(r["QuestionID"]).strip()
        ans = str(r["Response"]).strip()
        row_df = df[df["QuestionID"].astype(str).str.strip() == qid]
        if row_df.empty:
            continue
        row = row_df.iloc[0]
        if str(row["Type"]).strip().lower() != "mcq":
            continue
        if ans == get_correct_answer(row):
            total += 1
    return total

def likert_to_score(val):
    val = int(val)
    return val - 1   # 1→0, 2→1, 3→2, 4→3, 5→4

def calc_likert(df, responses):
    total = 0
    for r in responses:
        qid = str(r["QuestionID"]).strip()
        ans = r["Response"]
        row_df = df[df["QuestionID"].astype(str).str.strip() == qid]
        if row_df.empty:
            continue
        row = row_df.iloc[0]
        if str(row["Type"]).strip().lower() != "likert":
            continue
        try:
            total += likert_to_score(int(ans))
        except:
            pass
    return total


# -------------------------------------------------------
# LOAD SINGLE STUDENT SECTION DOC (SAFE)
# -------------------------------------------------------
@st.cache_data
def load_student_section(roll, section):
    doc_id = f"{roll}_{section.replace(' ', '_')}".replace("__", "_")
    doc = db.collection("student_responses").document(doc_id).get()
    if not doc.exists:
        return None, doc_id
    return doc.to_dict(), doc_id


# -------------------------------------------------------
# UI START
# -------------------------------------------------------
st.title("👩‍🏫 Faculty Evaluation Dashboard")

# FIRST — SELECT ROLL
roll = st.text_input("Enter Roll Number (exact):")

if not roll:
    st.stop()

# SECOND — SELECT SECTION
section = st.selectbox("Select Test Section", ALL_SECTIONS)

# LOAD FIRESTORE DOC
doc_data, doc_id = load_student_section(roll, section)

if doc_data is None:
    st.warning("❗ No responses found for this student for this section.")
    st.stop()

responses = doc_data["Responses"]
df = QBANKS[section]

# -------------------------------------------------------
# AUTO-EVALUATE ALWAYS
# -------------------------------------------------------
mcq_score = calc_mcq(df, responses)
likert_score = calc_likert(df, responses)

# -------------------------------------------------------
# MANUAL SECTION → show marking UI
# -------------------------------------------------------
text_marks = {}
text_total = 0

if section in MANUAL_EVAL:

    st.subheader("Faculty Scoring (Only Short Questions)")

    short_df = df[df["Type"].astype(str).str.lower() == "short"]

    for _, row in short_df.iterrows():
        qid = str(row["QuestionID"])
        qtext = row["Question"]

        # Student answer
        ans = next((r["Response"] for r in responses if str(r["QuestionID"]) == qid), "(no answer)")

        with st.expander(f"Q{qid}: {qtext}", expanded=False):
            st.markdown(f"**Student Answer:** {ans}")

            # Marks allowed = based on CSV
            if "MaxMarks" in row and not pd.isna(row["MaxMarks"]):
                maxm = int(row["MaxMarks"])
                options = list(range(0, maxm + 1))
            else:
                options = [0, 1]   # default short question scoring

            mark = st.radio(
                "Marks:",
                options,
                key=f"mark_{section}_{qid}",
                horizontal=True
            )

            text_marks[qid] = mark
            text_total += mark

else:
    # Auto sections have no manual text marks
    text_marks = {}
    text_total = 0


# -------------------------------------------------------
# GRAND TOTAL
# -------------------------------------------------------
grand_total = mcq_score + likert_score + text_total

st.markdown("---")
st.subheader(f"MCQ Score (Auto): {mcq_score}")
st.subheader(f"Likert Score (Auto): {likert_score}")
st.subheader(f"Text Marks (This Test): {text_total}")
st.subheader(f"GRAND TOTAL (All Tests) = {grand_total}")

# -------------------------------------------------------
# SAVE BUTTON
# -------------------------------------------------------
if st.button("💾 Save Evaluation for this Test"):
    db.collection("student_responses").document(doc_id).set({
        "Evaluation": {
            "mcq_total": mcq_score,
            "likert_total": likert_score,
            "text_total": text_total,
            "text_marks": text_marks,
            "final_total": grand_total
        }
    }, merge=True)

    st.success("Saved successfully!")
