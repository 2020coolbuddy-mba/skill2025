import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- FIREBASE INIT ----------------
def init_firestore():
    if not firebase_admin._apps:
        cred = credentials.Certificate(st.secrets["firebase"])
        firebase_admin.initialize_app(cred)
    return firestore.client()


db = init_firestore()


# ---------------- EXPORT LOGIC ----------------
TEST_SECTIONS = {
    "Adaptability_&_Learning": {
        "mcq": False,
        "likert": True,
        "text": False
    },
    "Aptitude_Test": {
        "mcq": True,
        "likert": False,
        "text": True
    },
    "Communication_Skills_-_Objective": {
        "mcq": True,
        "likert": False,
        "text": False
    },
    "Communication_Skills_-_Descriptive": {
        "mcq": False,
        "likert": False,
        "text": True
    }
}


def export_marks():
    rows = []

    docs = db.collection("student_responses").stream()

    for doc in docs:
        doc_id = doc.id  # example: "111AAA555_Aptitude_Test"
        data = doc.to_dict()
        eval_data = data.get("Evaluation", {})

        # Extract roll number and test section
        try:
            roll, section = doc_id.split("_", 1)
        except:
            continue

        # Check section applicability
        cfg = TEST_SECTIONS.get(section, {})

        mcq_score = eval_data.get("mcq_total") if cfg.get("mcq") else None
        likert_score = eval_data.get("likert_total") if cfg.get("likert") else None
        text_score = eval_data.get("final_total") if cfg.get("text") else None

        # Grand total appears in every document but use the same value
        grand_total = eval_data.get("grand_total", None)

        # Replace None with "N/A" for better Excel readability
        mcq_out = mcq_score if mcq_score is not None else "N/A"
        likert_out = likert_score if likert_score is not None else "N/A"
        text_out = text_score if text_score is not None else "N/A"

        row = {
            "Roll Number": roll,
            "Test Section": section.replace("_", " "),
            "MCQ Score": mcq_out,
            "Likert Score": likert_out,
            "Text Score": text_out,
            "Final Score (This Test)": text_score if isinstance(text_score, int) else mcq_score,
            "Grand Total (All Tests)": grand_total
        }

        rows.append(row)

    df = pd.DataFrame(rows)
    return df


# ---------------- STREAMLIT UI ----------------
st.title("📥 Download Student Marks")

if st.button("Generate Excel Report"):
    df = export_marks()

    st.dataframe(df)

    # Download Excel
    st.download_button(
        label="Download Excel File",
        data=df.to_csv(index=False).encode('utf-8'),
        file_name="student_marks.csv",
        mime="text/csv"
    )
