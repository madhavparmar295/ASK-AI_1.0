import pytest

from grievance_app.models import Category
from grievance_app.services.classifier import classify, flags, parse_keywords, score, tokenize
from grievance_app.services.classifier_eval import evaluate, load
from tests.grievance.conftest import login_as, new_issue

API = "/api/grievance"


def top(db, text):
    return classify(db, text)


# ---------- matching rules ----------

def test_tokenize_handles_punctuation_hyphens_and_devanagari():
    assert tokenize("Wi-Fi isn't working!!") == ["wi", "fi", "isn", "t", "working"]
    assert tokenize("मुझे रैगिंग का सामना") == ["मुझे", "रैगिंग", "का", "सामना"]


def test_keyword_kinds_and_weights():
    rules = parse_keywords("ac, leak*, air conditioner, hostel:3, wi fi:3, bed bug*")
    assert score(rules, "the AC is broken") == 1
    assert score(rules, "water leaking everywhere") == 1                      # prefix
    assert score(rules, "the aircon") == 0                                    # 'ac' is a whole word
    assert score(rules, "my air conditioner has a leak") == 2 + 1
    assert score(rules, "Wi-Fi in hostel") == 3 + 3
    assert score(rules, "bed bugs in my mattress") == 2


def test_category_suggestions(db_session, world):
    assert top(db_session, "AC in my room is not working")["suggested"]["name"] == "Hostel and housing"
    assert top(db_session, "Wi-Fi is down in the library block")["suggested"]["name"] == "IT and network"
    assert top(db_session, "I want a refund of my tuition fee")["suggested"]["name"] == "Fees and accounts"


def test_unknown_text_suggests_other_with_no_confidence(db_session, world):
    r = top(db_session, "something completely unrelated xyz")
    assert r["suggested"]["name"] == "Other" and r["confidence"] == "none" and r["alternatives"] == []


def test_confidence_levels(db_session, world):
    assert top(db_session, "Hostel warden not responding")["confidence"] == "high"
    assert top(db_session, "chair")["confidence"] == "low"                 # one weak keyword


def test_inactive_category_is_never_suggested(db_session, world):
    world["categories"]["Library"].active = False
    db_session.commit()
    assert top(db_session, "library books")["suggested"]["name"] != "Library"


def test_admin_keyword_change_changes_suggestion(db_session, world):
    cat = world["categories"]["Transport"]
    cat.keywords = (cat.keywords or "") + ", ferry:5"
    db_session.commit()
    assert top(db_session, "the ferry is late")["suggested"]["name"] == "Transport"


# ---------- confidential and urgent flags ----------

@pytest.mark.parametrize("text", [
    "A senior is ragging us", "he keeps harassing me", "I am being threatened", "She is stalking me",
    "caste based discrimination", "someone touched me", "I feel unsafe at night", "मुझे रैगिंग का सामना करना पड़ रहा है",
    "Mujhe dhamki mil rahi hai", "I was molested", "he is following me", "I want to die",
])
def test_confidential_terms_are_flagged(text):
    assert flags(text)["confidential"] is True


@pytest.mark.parametrize("text", [
    "The curtains are ragged", "AC not working", "Fee receipt missing", "I need a caste certificate",
])
def test_ordinary_text_is_not_flagged_confidential(text):
    assert flags(text)["confidential"] is False


def test_known_false_positive_is_documented():
    # "scared" appears in many harmless sentences. Accepted: a false alarm costs an officer a minute.
    assert flags("I am scared of the exam")["confidential"] is True
    # "fire" matches the fire ALARM test notice too.
    assert flags("The fire alarm test is tomorrow")["urgent"] is True


@pytest.mark.parametrize("text", ["smoke from the AC", "gas smell in the kitchen", "short circuit in my room",
                                  "student got an electric shock", "someone is injured", "aag lag gayi"])
def test_urgent_terms(text):
    assert flags(text)["urgent"] is True


def test_confidential_text_suggests_the_confidential_category(db_session, world):
    r = top(db_session, "Eve teasing near the bus stop every evening")
    assert r["confidential"] is True
    assert r["suggested"]["name"] == "Harassment, ragging, discrimination, safety"
    assert all(a["name"] != r["suggested"]["name"] for a in r["alternatives"])


# ---------- accuracy on the labelled files ----------

def test_accuracy_on_starter_set(db_session, world):
    out = evaluate(db_session, load("tests/grievance/data/classifier_samples.csv"))
    assert out["total"] >= 140
    assert out["accuracy"] >= 0.95
    assert out["confidential_recall"] == 1.0
    assert out["confidential_false_alarm_rate"] <= 0.03
    assert out["urgent_recall"] >= 0.85


def test_accuracy_on_blind_holdout(db_session, world):
    """Sentences written without looking at the keyword lists. Measured 77% (71% before widening the
    confidential terms). Unfamiliar wording falls back to 'Other', which asks the student to choose."""
    out = evaluate(db_session, load("tests/grievance/data/classifier_holdout.csv"))
    assert out["accuracy"] >= 0.70
    assert out["confidential_recall"] == 1.0


# ---------- endpoint and ticket creation ----------

def test_classify_endpoint(client, world):
    assert client.post(f"{API}/classify", json={"text": "AC not working"}).status_code == 401
    login_as(client, "ravi")
    r = client.post(f"{API}/classify", json={"text": "The AC in my hostel room is not working"})
    assert r.status_code == 200
    body = r.json()
    assert body["suggested"]["name"] == "Hostel and housing" and body["confidential"] is False
    assert set(body) == {"suggested", "confidence", "alternatives", "confidential", "urgent"}
    assert client.post(f"{API}/classify", json={"text": "x"}).status_code == 422
    assert client.post(f"{API}/classify", json={"text": "y" * 6000}).status_code == 422


def test_classify_endpoint_is_rate_limited(client, world, settings):
    settings.classify_rate_limit_per_minute = 2
    login_as(client, "ravi")
    codes = [client.post(f"{API}/classify", json={"text": "hostel fan"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_creating_a_ticket_applies_the_flags(client, world):
    login_as(client, "ravi")
    d = new_issue(client, world, category="Library", unit=None,
                  description="A senior is ragging me and there is smoke coming from the room").json()
    assert d["confidential"] is True and d["urgent"] is True


def test_student_cannot_lower_flags_by_unticking(client, world):
    login_as(client, "ravi")
    d = new_issue(client, world, category="Hostel and housing", unit="Hostel A", confidential=False,
                  description="He keeps harassing me every night in the hostel").json()
    assert d["confidential"] is True
