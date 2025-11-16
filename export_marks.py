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


# ------------------------------------------------------------
# CORRECT FIXED SECTION ORDER
# ------------------------------------------------------------
SECTION_ORDER = [
    "Adaptability & Learning",
    "Aptitude Test",
    "Communication Skills - Descriptive",
    "Communication Skills - Objective",
]


# ------------------------------------------------------------
# LOAD ALL DOCUMENTS
# ------------------------------------------------------------
rows = []

docs = db.collection("student_responses").stream()

for snap in docs:
    data = snap.to_dict() or {}

    roll = data.get("Roll")
    section = data.get("Section")
    evalb = data.get("Evaluation") or {}

    if not roll or not section:
        continue

    # Extract values
    mcq = evalb.get("mcq_total")
    likert = evalb.get("likert_total")
    text = evalb.get("final_total")
    grand = evalb.get("grand_total")

    # -----------------------------------------
    # COMPUTE FINAL SCORE PER TEST
    # -----------------------------------------
    if section == "Adaptability & Learning":              # Likert only
        final_score = likert if likert not in (None, "", 0) else "N/A"

    elif section == "Aptitude Test":                      # MCQ + Text
        m = mcq if isinstance(mcq, int) else 0
        t = text if isinstance(text, int) else 0
        final_score = m + t if (m + t) > 0 else "N/A"

    elif section == "Communication Skills - Descriptive": # Text only
        final_score = text if text not in (None, "", 0) else "N/A"

    elif section == "Communication Skills - Objective":   # MCQ only
        final_score = mcq if mcq not in (None, "", 0) else "N/A"

    else:
        final_score = "N/A"

    # Replace None/"" with N/A for export
    mcq = mcq if mcq not in (None, "") else "N/A"
    likert = likert if likert not in (None, "") else "N/A"
    text = text if text not in (None, "") else "N/A"
    grand = grand if grand not in (None, "") else "N/A"

    rows.append([
        roll,
        section,
        mcq,
        likert,
        text,
        final_score,
        grand,
    ])


# ------------------------------------------------------------
# BUILD DATAFRAME
# ------------------------------------------------------------
df = pd.DataFrame(rows, columns=[
    "Roll Number",
    "Section",
    "MCQ Score",
    "Likert Score",
    "Text Score",
    "Final Score (This Test)",
    "Grand Total (All Tests)",
])

# Apply section order
cat = pd.CategoricalDtype(categories=SECTION_ORDER, ordered=True)
df["Section"] = df["Section"].astype(cat)
df = df.sort_values(["Roll Number", "Section"])


# ------------------------------------------------------------
# SHOW GRAND TOTAL ONLY ON FIRST ROW OF EACH STUDENT
# ------------------------------------------------------------
clean_rows = []
last = None

for _, row in df.iterrows():
    rr = row.copy()
    if rr["Roll Number"] == last:
        rr["Grand Total (All Tests)"] = ""
    else:
        last = rr["Roll Number"]
    clean_rows.append(rr)

df_final = pd.DataFrame(clean_rows)


# ------------------------------------------------------------
# DISPLAY & DOWNLOAD
# ------------------------------------------------------------
st.dataframe(df_final, use_container_width=True)

csv = df_final.to_csv(index=False).encode("utf-8")

st.download_button(
    "⬇ Download CSV",
    csv,
    "evaluated_marks.csv",
    "text/csv",
)
