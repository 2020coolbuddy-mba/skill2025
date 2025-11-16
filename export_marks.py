import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import json

# -----------------------------
# FIREBASE INIT
# -----------------------------
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
        st.error(f"Firebase Init Failed: {e}")
        return None


db = init_firebase()
if not db:
    st.stop()

st.title("📤 Export Evaluated Marks")

# -----------------------------
# EXPORT LOGIC
# -----------------------------
rows = []

docs = db.collection("student_responses").stream()

for d in docs:
    data = d.to_dict()
    roll = data.get("Roll")
    section = data.get("Section")
    eval_block = data.get("Evaluation") or {}

    if not roll or not section:
        continue

    mcq = eval_block.get("mcq_total", None)
    likert = eval_block.get("likert_total", None)
    text = eval_block.get("final_total", None)
    final_score = 0

    # Final Score for the section
    if mcq not in (None, ""):
        final_score += mcq
    if likert not in (None, ""):
        final_score += likert
    if text not in (None, ""):
        final_score += text

    grand = eval_block.get("grand_total", None)

    # Replace missing values
    mcq = mcq if mcq not in (None, "") else "N/A"
    likert = likert if likert not in (None, "") else "N/A"
    text = text if text not in (None, "") else "N/A"

    rows.append([
        roll,
        section,
        mcq,
        likert,
        text,
        final_score if final_score != 0 else "N/A",
        grand       # We will clean this later
    ])


df = pd.DataFrame(rows, columns=[
    "Roll Number",
    "Test Section",
    "MCQ Score",
    "Likert Score",
    "Text Score",
    "Final Score (This Test)",
    "Grand Total (All Tests)"
])

# -----------------------------
# FIX GRAND TOTAL — show ONLY ONCE per student
# -----------------------------
df_sorted = df.sort_values(["Roll Number", "Test Section"])

clean_rows = []
last_roll = None

for idx, row in df_sorted.iterrows():
    r = row.copy()

    if r["Roll Number"] == last_roll:
        r["Grand Total (All Tests)"] = ""     # hide repeated values
    else:
        last_roll = r["Roll Number"]

    clean_rows.append(r)

df_final = pd.DataFrame(clean_rows)

st.dataframe(df_final)

csv = df_final.to_csv(index=False).encode("utf-8")

st.download_button(
    "⬇ Download Marks CSV",
    data=csv,
    file_name="student_marks.csv",
    mime="text/csv"
)
