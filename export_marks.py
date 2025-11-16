import streamlit as st
import pandas as pd
import json
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------------------------------------------------
# FIREBASE INITIALIZE
# -------------------------------------------------------------
@st.cache_resource
def init_firebase():
    if firebase_admin._apps:
        return firestore.client()

    try:
        # Load from Streamlit secrets
        cfg = dict(st.secrets["firebase"])
        cred = credentials.Certificate(cfg)
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except:
        st.error("Firebase initialization failed. Check credentials.")
        st.stop()

db = init_firebase()

st.title("📊 Download Student Marks (Auto + Manual Evaluation)")

# -------------------------------------------------------------
# LOAD QUESTION BANKS (same filenames used in your evaluation)
# -------------------------------------------------------------
@st.cache_data
def load_qbanks():
    return {
        "Aptitude Test": pd.read_csv("aptitude.csv"),
        "Adaptability & Learning": pd.read_csv("adaptability_learning.csv"),
        "Communication Skills - Objective": pd.read_csv("communication_skills_objective.csv"),
        "Communication Skills - Descriptive": pd.read_csv("communication_skills_descriptive.csv"),
    }

qbanks = load_qbanks()

# -------------------------------------------------------------
# LIKERT SCORING (your correct rule)
# 1 → 0
# 2 → 1
# 3 → 2
# 4 → 3
# 5 → 3
# -------------------------------------------------------------
def likert_to_score(v):
    v = int(v)
    if v == 1: return 0
    if v == 2: return 1
    if v == 3: return 2
    if v in [4, 5]: return 3
    return 0


# -------------------------------------------------------------
# MCQ SCORING
# -------------------------------------------------------------
def get_correct_answer(row):
    for col in ["Answer", "CorrectAnswer", "Correct", "Ans", "AnswerKey"]:
        if col in row and not pd.isna(row[col]):
            return str(row[col]).strip()
    return None


def calc_mcq(df, responses):
    score = 0
    for r in responses:
        qid = str(r["QuestionID"])
        ans = str(r["Response"]).strip()
        row_df = df[df["QuestionID"].astype(str) == qid]
        if row_df.empty:
            continue
        row = row_df.iloc[0]
        if row["Type"] != "mcq":
            continue
        correct = get_correct_answer(row)
        if correct and ans == correct:
            score += 1
    return score


# -------------------------------------------------------------
# LIKERT SCORING
# -------------------------------------------------------------
def calc_likert(df, responses):
    total = 0
    for r in responses:
        qid = str(r["QuestionID"])
        ans = r["Response"]
        row_df = df[df["QuestionID"].astype(str) == qid]
        if row_df.empty:
            continue
        row = row_df.iloc[0]
        if str(row["Type"]).lower() != "likert":
            continue
        total += likert_to_score(ans)
    return total


# -------------------------------------------------------------
# DOWNLOAD BUTTON
# -------------------------------------------------------------
if st.button("📥 Generate Marks Excel File"):
    docs = list(db.collection("student_responses").stream())
    rows = []
    grand_totals = {}

    for doc in docs:
        data = doc.to_dict() or {}
        roll = data.get("Roll")
        section = data.get("Section")
        responses = data.get("Responses", [])
        evaldata = data.get("Evaluation", {})

        if not roll or not section:
            continue

        df = qbanks.get(section)

        if df is None:
            continue

        mcq = calc_mcq(df, responses)
        likert = calc_likert(df, responses)
        text = int(evaldata.get("text_total", 0))

        final_score = mcq + likert + text

        grand_totals.setdefault(roll, 0)
        grand_totals[roll] += final_score

        rows.append({
            "Roll Number": roll,
            "Test Section": section,
            "MCQ Score": mcq,
            "Likert Score": likert,
            "Text Score": text,
            "Final Score (This Test)": final_score,
            "Grand Total (All Tests)": 0,  # filled later
        })

    # Second pass: fill final totals
    for row in rows:
        row["Grand Total (All Tests)"] = grand_totals[row["Roll Number"]]

    df_export = pd.DataFrame(rows)

    # Show preview
    st.dataframe(df_export)

    # Download
    st.download_button(
        label="💾 Download Excel / CSV",
        data=df_export.to_csv(index=False).encode("utf-8"),
        file_name="final_student_marks.csv",
        mime="text/csv"
    )

    st.success("Report generated successfully ✔️")
