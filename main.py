import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import time
import json
import re

import streamlit as st

# ---------------- PAGE CONFIG ----------------
st.set_page_config(page_title="SKILL - 2025", layout="wide")
st.title("🧠 SKILL - 2025")

# ---------------- FIREBASE CONNECTION ----------------
@st.cache_resource
def init_firebase():
    try:
        if not firebase_admin._apps:
            # ✅ Use secrets when deployed on Streamlit Cloud
            if "firebase" in st.secrets:
                firebase_config = dict(st.secrets["firebase"])
                cred = credentials.Certificate(firebase_config)
                firebase_admin.initialize_app(cred)
            else:
                # ✅ Only used locally when secrets aren't available
                st.warning("⚠️ Using local firebase_key.json (not found on cloud).")
                import json
                with open("firebase_key.json", "r", encoding="utf-8") as f:
                    firebase_config = json.load(f)
                cred = credentials.Certificate(firebase_config)
                firebase_admin.initialize_app(cred)

        return firestore.client()
    except Exception as e:
        st.error(f"❌ Firebase initialization failed: {e}")
        return None

db = init_firebase()

# ---------------- CSV FILES ----------------
files = {
    "Aptitude Test": "aptitude.csv",
    "Adaptability & Learning": "adaptability_learning.csv",
    "Communication Skills - Objective": "communication_skills_objective.csv",
    "Communication Skills - Descriptive": "communication_skills_descriptive.csv",
}

# ---- inputs ----
name = st.text_input("Enter Your Name (letters only)", value="")
roll  = st.text_input("Enter Roll Number (e.g., 25BBAB001)", value="")

# ---- validator (must be defined before you use it) ----
def valid_name(n: str) -> bool:
    if not isinstance(n, str):
        return False
    n = n.strip()
    if not n:
        return False
    # letters + single spaces between words (no digits/symbols)
    return bool(re.fullmatch(r"[A-Za-z]+(?: [A-Za-z]+)*", n))

name_ok = valid_name(name)

# live feedback
if name and not name_ok:
    st.error("Name should contain only letters and spaces (e.g., 'Ravi Kumar').")

# normalized title case, if you want to save/display neatly
clean_name = " ".join(part.capitalize() for part in name.split()) if name_ok else name


# ---------------- MAIN APP ----------------
if name and roll:
    st.success(f"Welcome, {name}! Please Choose a Test in the Dropdown Below.")
    section = st.selectbox("Select Section", list(files.keys()))
    
    if section == "Communication Skills - Descriptive":
        st.info("📝 Q1 to Q10 - Find the error and correct the sentence.")
               
    if section:
        try:
            df = pd.read_csv(files[section])
        except FileNotFoundError:
            st.error(f"❌ File '{files[section]}' not found. Please check the file name.")
            st.stop()

        st.subheader(f"📘 {section}")
        st.write("Answer all the questions below and click **Submit**.")

        responses = []

        for idx, row in df.iterrows():
            qid = row.get("QuestionID", f"Q{idx+1}")
            qtext = str(row.get("Question", "")).strip()
            qtype = str(row.get("Type", "")).strip().lower()

            # ---- Instructional text only ----
            if qtype == "info":
                st.markdown(f"### 📝 {qtext}")
                st.markdown("---")
                continue

            st.markdown(f"**Q{idx+1}. {qtext}**")

            # ---- Likert scale ----
            if qtype == "likert":
                scale_min = int(row.get("ScaleMin", 1))
                scale_max = int(row.get("ScaleMax", 5))
                response = st.slider(
                    "Your Response:",
                    min_value=scale_min,
                    max_value=scale_max,
                    value=(scale_min + scale_max) // 2,
                    key=f"q{idx}_{section}"
                )

            # ---- Multiple Choice ----
            elif qtype == "mcq":
                options = [
                    str(row.get(f"Option{i}", "")).strip()
                    for i in range(1, 5)
                    if pd.notna(row.get(f"Option{i}")) and str(row.get(f"Option{i}")).strip() != ""
                ]
                if options:
                    response = st.radio("Your Answer:", options, key=f"q{idx}_{section}")
                else:
                    st.warning(f"No options available for {qid}")
                    response = ""

            # ---- Short / Descriptive ----
            elif qtype == "short":
                response = st.text_area("Your Answer:", key=f"q{idx}_{section}")

            # ---- Unknown / Empty ----
            else:
                st.info(f"⚠️ Unknown question type '{qtype}' for {qid}.")
                response = ""

            responses.append({
                "QuestionID": qid,
                "Question": qtext,
                "Response": response,
                "Type": qtype,
            })
            st.markdown("---")

        # ---------------- SUBMIT ----------------
        if st.button("✅ Submit"):
            if not db:
                st.error("❌ Database connection failed. Cannot save responses.")
            else:
                with st.spinner("Saving your responses..."):
                    data = {
                        "Name": name,
                        "Roll": roll,
                        "Section": section,
                        "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "Responses": responses,
                    }
                    try:
                        # ✅ Use document ID based on roll and section
                        doc_ref = db.collection("student_responses").document(
                            f"{roll}_{section.replace(' ', '_')}"
                        )
        
                        # ✅ This will overwrite the same document instead of creating a duplicate
                        doc_ref.set(data, merge=True)
        
                        st.success("✅ Your responses have been successfully submitted (updated if existing)!")
                    except Exception as e:
                        st.error(f"❌ Error saving to database: {e}")
    st.markdown(
        "<p style='color:#007BFF; font-weight:600;'>⌨️ Press <b>Home</b> on the keyboard to return to the top of the page.</p>",
        unsafe_allow_html=True,
    )

else:
    st.info("👆 Please enter your Name and Roll Number to start.")

# Tighten top spacing so title & fields sit higher
st.markdown("""
<style>
/* Pull the whole page content up a bit */
div.block-container {
    padding-top: 2.0rem;      /* default is ~6rem; lower = higher on the page */
    padding-bottom: 1.5rem;   /* optional */
}

/* Nudge the h1 title if you want it even closer to the top */
h1, .stTitle {
    margin-top: -0.2rem;      /* make more negative to move further up */
}
</style>
""", unsafe_allow_html=True)








































