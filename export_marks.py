import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# ----------------------------
# FIREBASE INITIALIZATION
# ----------------------------
def init_firestore():
    if firebase_admin._apps:
        return firestore.client()

    cfg = st.secrets["firebase"]  # You already configured this in Streamlit
    cred = credentials.Certificate(cfg)
    firebase_admin.initialize_app(cred)
    return firestore.client()


db = init_firestore()


# ----------------------------
# PLACEHOLDER FOR NON-APPLICABLE
# ----------------------------
NOT_APPLICABLE = "None"     # You may change to "NA", "-", "" etc.


# ----------------------------
# SECTION APPLICABILITY MAP
# ----------------------------
# Only these sections have MCQ / Likert / Text scores
SECTION_RULES = {
    "Adaptability & Learning": {"mcq": False, "likert": True,  "text": False},
    "Aptitude Test":           {"mcq": True,  "likert": False, "text": True},
    "Communication Skills - Descriptive": {"mcq": False, "likert": False, "text": True},
    "Communication Skills - Objective":   {"mcq": True,  "likert": False, "text": False},
}


# ----------------------------
# HELPER FUNCTION: Apply NA rules
# ----------------------------
def apply_na(section, mcq, likert, text):
    rules = SECTION_RULES.get(section, None)

    if rules is None:
        # Unknown section → leave values as is
        return mcq, likert, text

    mcq_final   = mcq   if rules["mcq"]   else NOT_APPLICABLE
    likert_final = likert if rules["likert"] else NOT_APPLICABLE
    text_final   = text   if rules["text"]   else NOT_APPLICABLE

    return mcq_final, likert_final, text_final


# ----------------------------
# STREAMLIT PAGE UI
# ----------------------------
st.title("📥 Download Student Marks Report")

if st.button("Generate Marks Excel File"):
    docs = db.collection("student_responses").stream()

    all_rows = []

    for doc in docs:
        data = doc.to_dict()
        roll = data.get("roll", "")
        section = data.get("section", "")

        mcq = data.get("mcq_total", 0)
        likert = data.get("likert_total", 0)
        text = data.get("text_total", 0)
        final_score = data.get("final_total", 0)
        grand_total = data.get("grand_total", 0)

        # Apply NA rules based on the section
        mcq_out, likert_out, text_out = apply_na(section, mcq, likert, text)

        row = {
            "Roll Number": roll,
            "Test Section": section,
            "MCQ Score": mcq_out,
            "Likert Score": likert_out,
            "Text Score": text_out,
            "Final Score (This Test)": final_score,
            "Grand Total (All Tests)": grand_total,
        }
        all_rows.append(row)

    df = pd.DataFrame(all_rows)

    # ----------------------------
    # Download Button
    # ----------------------------
    st.success("Marks file generated successfully!")

    st.download_button(
        label="⬇ Download Excel File",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="Student_Marks_Report.csv",
        mime="text/csv"
    )

    st.dataframe(df)
