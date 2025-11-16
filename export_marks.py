import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import json

# -------------------------------------
# Firebase init
# -------------------------------------
@st.cache_resource
def init_firebase():
    if firebase_admin._apps:
        return firestore.client()

    try:
        if "firebase" in st.secrets:
            cfg = dict(st.secrets["firebase"])
        else:
            with open("firebase_key.json") as f:
                cfg = json.load(f)

        cred = credentials.Certificate(cfg)
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"Firebase init failed: {e}")
        return None


db = init_firebase()
if not db:
    st.stop()

st.title("📤 Export Evaluated Marks")


# ----------------------------------------------------
# Section Order
# ----------------------------------------------------
SECTION_ORDER = [
    "Adaptability & Learning",
    "Aptitude Test",
    "Communication Skills - Descriptive",
    "Communication Skills - Objective",
]


# ----------------------------------------------------
# Fetch all documents
# ----------------------------------------------------
docs = db.collection("student_responses").stream()

# roll → { section → scores }
records = {}

for snap in docs:
    data = snap.to_dict() or {}

    roll = data.get("Roll")
    section = data.get("Section")

    if not roll or not section:
        continue

    evalb = data.get("Evaluation") or {}

    mcq = evalb.get("mcq_total")
    likert = evalb.get("likert_total")
    text = evalb.get("text_total")
    final_test_score = evalb.get("final_total")

    # Store clean value or N/A
    def clean(v):
        return v if (v not in (None, "", {}, [])) else "N/A"

    mcq = clean(mcq)
    likert = clean(likert)
    text = clean(text)
    final_test_score = clean(final_test_score)

    if roll not in records:
        records[roll] = {}

    records[roll][section] = {
        "mcq": mcq,
        "likert": likert,
        "text": text,
        "final_test_score": final_test_score
    }


# ----------------------------------------------------
# Build final export rows
# ----------------------------------------------------
rows = []

for roll, tests in records.items():

    # compute grand total from per-test final scores
    grand_total = 0
    for sec in SECTION_ORDER:
        block = tests.get(sec, {})
        v = block.get("final_test_score")
        if isinstance(v, int):
            grand_total += v

    # Now create row per test (in correct order)
    for i, sec in enumerate(SECTION_ORDER):
        block = tests.get(sec, {})
        mcq = block.get("mcq", "N/A")
        likert = block.get("likert", "N/A")
        text = block.get("text", "N/A")
        final_test_score = block.get("final_test_score", "N/A")

        # Show grand total only on 1st row of each roll
        if i == 0:
            g = grand_total
        else:
            g = ""

        rows.append([
            roll,
            sec,
            mcq,
            likert,
            text,
            final_test_score,
            g,
        ])

df = pd.DataFrame(rows, columns=[
    "Roll Number",
    "Section",
    "MCQ Score",
    "Likert Score",
    "Text Score",
    "Final Score (This Test)",
    "Grand Total (All Tests)"
])

st.dataframe(df)

csv = df.to_csv(index=False).encode("utf-8")
st.download_button("⬇ Download CSV", csv, "evaluated_marks.csv", "text/csv")
