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

# -------------------------------------
# Correct section order & scoring rules
# -------------------------------------
SECTION_ORDER = [
    "Adaptability & Learning",
    "Aptitude Test",
    "Communication Skills - Descriptive",
    "Communication Skills - Objective",
]

rows = []

docs = db.collection("student_responses").stream()

for snap in docs:
    data = snap.to_dict() or {}

    roll = data.get("Roll")
    section = data.get("Section")
    evalb = data.get("Evaluation") or {}

    if not roll or not section:
        continue

    mcq = evalb.get("mcq_total")
    likert = evalb.get("likert_total")
    text = evalb.get("final_total")
    grand = evalb.get("grand_total")

    # ---------- FINAL SCORE PER TEST ----------
    # A) Adaptability & Learning  -> Likert only
    if section == "Adaptability & Learning":
        final_score = likert if likert not in (None, "") else "N/A"

    # B) Aptitude Test -> MCQ + Text
    elif section == "Aptitude Test":
        m = mcq if mcq not in (None, "") else 0
        t = text if text not in (None, "") else 0
        s = m + t
        final_score = s if s != 0 else "N/A"

    # C) Communication Skills – Descriptive -> Text only
    elif section == "Communication Skills - Descriptive":
        final_score = text if text not in (None, "") else "N/A"

    # D) Communication Skills – Objective -> MCQ only
    elif section == "Communication Skills - Objective":
        final_score = mcq if mcq not in (None, "") else "N/A"

    else:
        final_score = "N/A"

    # normalise empty to "N/A" for export
    mcq = mcq if mcq not in (None, "") else "N/A"
    likert = likert if likert not in (None, "") else "N/A"
    text = text if text not in (None, "") else "N/A"

    rows.append([
        roll,
        section,
        mcq,
        likert,
        text,
        final_score,
        grand,
    ])

df = pd.DataFrame(rows, columns=[
    "Roll Number",
    "Section",
    "MCQ Score",
    "Likert Score",
    "Text Score",
    "Final Score (This Test)",
    "Grand Total (All Tests)",
])

# -------------------------------------
# Apply custom section order per roll
# -------------------------------------
cat = pd.CategoricalDtype(categories=SECTION_ORDER, ordered=True)
df["Section"] = df["Section"].astype(cat)

df = df.sort_values(["Roll Number", "Section"])

# Only show Grand Total on the first section row of each roll
clean_rows = []
last_roll = None
for _, r in df.iterrows():
    rr = r.copy()
    if rr["Roll Number"] == last_roll:
        rr["Grand Total (All Tests)"] = ""
    else:
        last_roll = rr["Roll Number"]
    clean_rows.append(rr)

df_final = pd.DataFrame(clean_rows)

st.dataframe(df_final)

csv = df_final.to_csv(index=False).encode("utf-8")

st.download_button(
    "⬇ Download CSV",
    csv,
    "evaluated_marks.csv",
    "text/csv",
)
