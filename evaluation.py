import streamlit as st
import pandas as pd
import json
import firebase_admin
from firebase_admin import credentials, firestore

# ============================================================
# PAGE SETTINGS
# ============================================================
st.set_page_config(page_title="Faculty Evaluation Dashboard", layout="wide")
st.title("🧑‍🏫 Faculty Evaluation Dashboard")


# ============================================================
# FIREBASE INITIALIZATION
# ============================================================
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
        st.error(f"Firebase Init Error: {e}")
        return None

    return firestore.client()


db = init_firebase()
if db is None:
    st.stop()


# ============================================================
# LOAD CSVs (CACHED)
# ============================================================
@st.cache_data
def load_questions():
    return {
        "Aptitude Test": pd.read_csv("aptitude.csv"),
        "Communication Skills - Descriptive": pd.read_csv("communication_skills_descriptive.csv"),
        "Adaptability & Learning": pd.read_csv("adaptability_learning.csv"),
        "Communication Skills - Objective": pd.read_csv("communication_skills_objective.csv"),
    }


question_banks = load_questions()


# ============================================================
# AUTO-EVALUATED TESTS (MCQ + LIKERT)
# ============================================================
AUTO_EVAL_TESTS = ["Adaptability & Learning", "Communication Skills - Objective"]

MANUAL_TESTS = [
    "Aptitude Test",
    "Communication Skills - Descriptive"
]


# ============================================================
# MARK SCHEME RULES
# ============================================================
MARK_SCHEMES = {
    12: [0,1,2,3],
    13: [0,1,2,3],
    14: [0,1,2,3],
    16: [0,1,2,3],
    17: [0,1,2,3],
    18: [0,1,2,3],

    22: [0,1,2],
    23: [0,1,2],
    24: [0,1,2],
    25: [0,1,2],
    28: [0,1,2],
    29: [0,1,2],
    30: [0,1,2],
    34: [0,1,2],
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_correct_answer(row):
    for col in ["Correct", "Answer", "Ans"]:
        if col in row and pd.notna(row[col]):
            return str(row[col]).strip()
    return None


def likert_to_score(v):
    return int(v) - 1  # 1→0, 2→1, 3→2, 4→3, 5→4


def calc_mcq(df, responses):
    score = 0
    for r in responses:
        qid = str(r["QuestionID"])
        student_ans = str(r["Response"]).strip()

        row_df = df[df["QuestionID"].astype(str) == qid]
        if row_df.empty:
            continue
        row = row_df.iloc[0]

        if str(row["Type"]).lower() != "mcq":
            continue

        correct = get_correct_answer(row)
        if correct == student_ans:
            score += 1

    return score


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


def auto_evaluate(section, doc_id, df, responses):
    mcq_total = calc_mcq(df, responses)
    likert_total = calc_likert(df, responses)
    final_total = mcq_total + likert_total

    db.collection("student_responses").document(doc_id).set({
        "Evaluation": {
            "mcq_total": mcq_total,
            "likert_total": likert_total,
            "text_total": 0,
            "text_marks": {},
            "final_total": final_total
        }
    }, merge=True)

    return final_total


def compute_grand_total(docs):
    total = 0
    for d in docs:
        data = d.to_dict()
        eval_data = data.get("Evaluation", {})
        total += eval_data.get("final_total", 0)
    return total


# ============================================================
# READ ALL STUDENT RESPONSES (CACHED)
# ============================================================
@st.cache_data
def load_student_map():
    docs = list(db.collection("student_responses").stream())
    student_map = {}

    for d in docs:
        data = d.to_dict()
        roll = data.get("Roll")
        section = data.get("Section")
        if roll is None:
            continue
        if roll not in student_map:
            student_map[roll] = []
        student_map[roll].append((section, d.id))
    return student_map


student_map = load_student_map()
all_students = sorted(student_map.keys())


# ============================================================
# STUDENT DROPDOWN — SHOW EVALUATED STATUS
# ============================================================
display_names = []
for roll in all_students:
    docs = student_map[roll]
    completed = False

    for sec, docid in docs:
        if sec in MANUAL_TESTS:
            d = db.collection("student_responses").document(docid).get().to_dict()
            if d and "Evaluation" in d and d["Evaluation"].get("text_total", None) is not None:
                completed = True

    label = f"{roll}  ✔ Evaluated" if completed else f"{roll}  ✖ Pending"
    display_names.append(label)

choice = st.selectbox("Select Student:", display_names)
selected_roll = choice.split()[0]


# ============================================================
# AUTO-EVALUATE REQUIRED TESTS
# ============================================================
for section, doc_id in student_map[selected_roll]:
    if section in AUTO_EVAL_TESTS:
        data = db.collection("student_responses").document(doc_id).get().to_dict()
        if data:
            df = question_banks[section]
            responses = data["Responses"]
            auto_evaluate(section, doc_id, df, responses)


# ============================================================
# MANUAL TEST DROPDOWN
# ============================================================
tests_taken = [sec for (sec, _) in student_map[selected_roll] if sec in MANUAL_TESTS]
selected_test = st.selectbox("Select Test for Manual Evaluation", tests_taken)

doc_id = [d for (sec, d) in student_map[selected_roll] if sec == selected_test][0]
doc_data = db.collection("student_responses").document(doc_id).get().to_dict()
responses = doc_data["Responses"]

df = question_banks[selected_test]


# ============================================================
# FACULTY MARK ENTRY
# ============================================================
text_total = 0
marks_given = {}

st.subheader("📝 Manual Evaluation")

for _, row in df[df["Type"] == "short"].iterrows():
    qid = int(row["QuestionID"])
    qtext = row["Question"]

    student_ans = next((r["Response"] for r in responses if str(r["QuestionID"]) == str(qid)), "(no answer)")

    if qid in MARK_SCHEMES:
        scale = MARK_SCHEMES[qid]
    else:
        scale = [0, 1]   # default

    with st.expander(f"Q{qid}: {qtext}", expanded=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**Student Answer:** {student_ans}")
        with col2:
            mark = st.radio("Marks:", scale, horizontal=True, key=f"mark_{qid}")
        marks_given[qid] = mark
        text_total += mark


# ============================================================
# TOTALS
# ============================================================
all_docs = [db.collection("student_responses").document(docid).get()
            for (_, docid) in student_map[selected_roll]]

grand_total_before = compute_grand_total(all_docs)
old_eval = doc_data.get("Evaluation", {})
previous_final = old_eval.get("final_total", 0)

grand_total = grand_total_before - previous_final + text_total

st.subheader(f"GRAND TOTAL (All Tests) = {grand_total}")


# ============================================================
# SAVE BUTTON
# ============================================================
if st.button("💾 Save Evaluation"):
    db.collection("student_responses").document(doc_id).set({
        "Evaluation": {
            "text_marks": marks_given,
            "text_total": text_total,
            "final_total": text_total  # only this test
        }
    }, merge=True)

    st.success("Saved Successfully ✓ — Dropdown will show updated status after refresh.")
