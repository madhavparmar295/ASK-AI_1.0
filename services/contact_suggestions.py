"""
Contact Suggestions Service
Matches user queries to relevant IITJ contact emails when the AI
cannot find an answer in the uploaded documents.
"""

CONTACT_MAP = [
    {
        "keywords": ["dining", "mess", "food", "menu", "hygiene", "canteen", "meal", "lunch", "dinner", "breakfast"],
        "name": "Dining Committee",
        "email": "dining@iitj.ac.in",
    },
    {
        "keywords": ["hostel", "room", "accommodation", "dorm", "dormitory", "maintenance", "facility", "facilities", "warden"],
        "name": "Hostel Management Committee (HMC)",
        "email": "hmc@iitj.ac.in",
    },
    {
        "keywords": ["welfare", "scholarship", "fellowship", "stipend", "grievance", "complaint", "mental health", "counselling"],
        "name": "Student Welfare Committee (SWC)",
        "email": "swc@iitj.ac.in",
    },
    {
        "keywords": ["course", "registration", "erp", "enroll", "enrollment", "add", "drop", "elective"],
        "name": "ERP & Registration",
        "email": "registration@iitj.ac.in",
    },
    {
        "keywords": ["exam", "admit card", "marks", "grade", "evaluation", "paper", "result", "cgpa", "sgpa", "backlog", "revaluation"],
        "name": "Examination Cell",
        "email": "examhelp@iitj.ac.in",
    },
    {
        "keywords": ["transcript", "grade card", "degree", "certificate", "document", "verification", "bonafide"],
        "name": "Transcript Office",
        "email": "transcript@iitj.ac.in",
    },
    {
        "keywords": ["undergraduate", "ug", "b.tech", "btech", "bachelor"],
        "name": "Office of Academics (UG)",
        "email": "office_academics_ug@iitj.ac.in",
    },
    {
        "keywords": ["postgraduate", "pg", "m.tech", "mtech", "msc", "master", "phd", "doctoral", "thesis"],
        "name": "Office of Academics (PG)",
        "email": "office_academics_pg@iitj.ac.in",
    },
    {
        "keywords": ["timetable", "time table", "schedule", "class", "clash", "lecture", "slot"],
        "name": "Faculty In-Charge (Time Table)",
        "email": "fic_tt@iitj.ac.in",
    },
    {
        "keywords": ["academic policy", "semester", "academic", "policy", "regulation", "rule", "dean academic"],
        "name": "Dean of Academic Affairs",
        "email": "dean_academics@iitj.ac.in",
    },
    {
        "keywords": ["digital", "it", "internet", "network", "wifi", "vpn", "email", "institute email", "portal"],
        "name": "DDIA (IT Services)",
        "email": "ddia@iitj.ac.in",
    },
    {
        "keywords": ["medical", "health", "doctor", "hospital", "emergency", "sick", "medicine", "phc", "clinic"],
        "name": "Primary Health Centre (PHC)",
        "email": "phc@iitj.ac.in",
    },
    {
        "keywords": ["sports", "gym", "ground", "stadium", "tournament", "game", "cricket", "football", "basketball"],
        "name": "GS, Sports Council",
        "email": "gensecy_sports@iitj.ac.in",
    },
    {
        "keywords": ["cultural", "culture", "club", "literary", "fest", "event", "drama", "music", "dance", "art"],
        "name": "GS, Cultural & Literary Council",
        "email": "gensecy_clc@iitj.ac.in",
    },
    {
        "keywords": ["placement", "internship", "career", "job", "technical", "coding", "hackathon", "workshop"],
        "name": "GS, ACT Council",
        "email": "gensecy_act@iitj.ac.in",
    },
    {
        "keywords": ["alumni", "international", "startup", "entrepreneurship", "innovation", "incubation"],
        "name": "GS, AIRE Council",
        "email": "gensecy_aire@iitj.ac.in",
    },
    {
        "keywords": ["faculty", "professor", "teacher", "instructor", "contact faculty"],
        "name": "All Faculty",
        "email": "faculty@iitj.ac.in",
    },
    {
        "keywords": ["hod", "head of department", "department head"],
        "name": "Head of Department",
        "email": "heads@iitj.ac.in",
    },
    {
        "keywords": ["gymkhana", "student body", "student council", "president", "gymkhana president"],
        "name": "President, Student Gymkhana",
        "email": "president_ss@iitj.ac.in",
    },
    {
        "keywords": ["vice president", "vp gymkhana", "student representative", "student concern"],
        "name": "Vice President, Student Gymkhana",
        "email": "vicepresident_ss@iitj.ac.in",
    },
]


def get_suggestions(question: str, max_suggestions: int = 2) -> list[dict]:
    """
    Returns a ranked list of relevant contacts for a given question.
    Each contact is scored by how many of its keywords appear in the question.
    """
    question_lower = question.lower()
    scored = []

    for contact in CONTACT_MAP:
        score = sum(1 for kw in contact["keywords"] if kw in question_lower)
        if score > 0:
            scored.append((score, contact))

    # Sort by descending score, pick top N
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:max_suggestions]]


def build_fallback_message(question: str) -> str:
    """
    Builds a helpful fallback message with contact suggestions when
    the AI cannot find the answer in documents.
    Plain text only - no markdown, no emojis.
    """
    suggestions = get_suggestions(question)

    base = "I could not find the answer in the provided documents."

    if not suggestions:
        return (
            base
            + "\n\nFor further assistance, you may contact the Student Gymkhana at president_ss@iitj.ac.in"
        )

    lines = [base, "\nYou may contact the following for further assistance:\n"]
    for s in suggestions:
        lines.append(f"  {s['name']}")
        lines.append(f"  {s['email']}\n")

    return "\n".join(lines)
