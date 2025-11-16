import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import json


# ------------------------------------------------
# FIREBASE INITIALIZATION (Stable Version)
# ------------------------------------------------
@st.cache_resource
def init_firebase():
    if firebase_admin._apps:
        return firestore.client()

    try:
        if "firebase" in st.secrets:
            cfg = dict(st.secrets["firebase"])
            cred = credentials.Certificate(cfg)
            firebase_admin.initialize_app(cred)
        else:
            with open("firebase_key.json", "r") as f:
                cfg = json.load(f)
            cred = credentials.Certificate(cfg)
            firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase initialization failed: {e}")
        return None

    return firestore.client()


db = init_firebase()
if db is None:
    st.stop()


# ------------------------------------------------
#   UI HEADER
# ------------------------------------------------
st.title("📥 Download Student Marks")
st.write("This tool exports **all evaluated test results** stored in the `student_responses` Firestore collection.")


# ------------------------------------------------
#   FETCH ALL MARKS FROM FIRESTORE
# ------------------------------------------------
def fetch_marks():
    docs = db.collection("student_responses").stream()
    rows = []

    for doc in docs:
        data = doc.to_dict()

        roll = data.get("Roll")
        section = data.get("Section")
        eval_data = data.get("Evaluation", {})

        rows.append({
            "Roll Number": roll,
            "Test Section": section,
            "MCQ Score": eval_data.get("mcq_total", 0),
            "Likert Score": eval_data.get("likert_total", 0),
            "Text Score": eval_data.get("text_total", 0),
            "Final Score (This Test)": eval_data.get("final_total", 0),
            "Grand Total": eval_data.get("grand_total", 0)
        })

    df = pd.DataFrame(rows)
    return df


# ------------------------------------------------
#   DOWNLOAD BUTTON
# ------------------------------------------------
if st.button("📥 Generate CSV File"):
    df = fetch_marks()

    if df.empty:
        st.warning("No student data found in Firestore.")
    else:
        csv = df.to_csv(index=False).encode("utf-8")

        st.success("CSV file generated successfully!")
        st.download_button(
            label="⬇ Download Student Marks CSV",
            data=csv,
            file_name="student_marks.csv",
            mime="text/csv"
        )

        st.dataframe(df, use_container_width=True)
