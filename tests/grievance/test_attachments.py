import os

import pytest

from grievance_app.models import Attachment
from tests.grievance.conftest import login_as, logout, new_issue

API = "/api/grievance"

JPG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + os.urandom(2000)
PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(2000)
PDF = b"%PDF-1.7\n" + os.urandom(2000)


@pytest.fixture()
def ticket(client, world, upload_dir):
    login_as(client, "ravi")
    return new_issue(client, world).json()["id"]


def up(client, tid, content, name="photo.jpg", mime="image/jpeg"):
    return client.post(f"{API}/issues/{tid}/attachments", files={"file": (name, content, mime)})


@pytest.mark.parametrize("content,name,mime,stored_mime", [
    (JPG, "ac.jpg", "image/jpeg", "image/jpeg"),
    (PNG, "ac.png", "image/png", "image/png"),
    (PDF, "receipt.pdf", "application/pdf", "application/pdf"),
])
def test_accepts_allowed_types_unchanged(client, ticket, upload_dir, content, name, mime, stored_mime):
    r = up(client, ticket, content, name, mime)
    assert r.status_code == 201, r.text
    assert r.json()["mime_type"] == stored_mime and r.json()["size_bytes"] == len(content)
    dl = client.get(f"{API}/attachments/{r.json()['id']}")
    assert dl.status_code == 200 and dl.content == content           # byte-for-byte identical
    assert "attachment" in dl.headers["content-disposition"]
    assert dl.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in dl.headers["cache-control"]


def test_stored_name_is_random_and_file_is_in_upload_dir(client, ticket, upload_dir, db_session):
    up(client, ticket, JPG, "my-secret-name.jpg")
    att = db_session.query(Attachment).one()
    assert att.stored_name != "my-secret-name.jpg" and len(att.stored_name) > 30
    assert (upload_dir / att.stored_name).is_file()
    assert [p.name for p in upload_dir.iterdir()] == [att.stored_name]    # no leftover .part files


def test_type_is_checked_from_content_not_name(client, ticket, upload_dir):
    exe = b"MZ\x90\x00" + os.urandom(500)
    assert up(client, ticket, exe, "virus.jpg", "image/jpeg").status_code == 415
    assert up(client, ticket, b"PK\x03\x04" + os.urandom(500), "doc.docx",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document").status_code == 415
    assert up(client, ticket, b"<html><script>alert(1)</script></html>", "x.png", "image/png").status_code == 415
    assert not upload_dir.exists() or list(upload_dir.iterdir()) == []   # nothing stored


def test_real_pdf_with_wrong_name_is_labelled_by_content(client, ticket, upload_dir):
    r = up(client, ticket, PDF, "notes.png", "image/png")
    assert r.status_code == 201 and r.json()["mime_type"] == "application/pdf"
    dl = client.get(f"{API}/attachments/{r.json()['id']}")
    assert dl.headers["content-type"] == "application/pdf" and dl.headers["content-disposition"].count(".pdf") >= 1


def test_filename_is_sanitised(client, ticket, upload_dir):
    r = up(client, ticket, JPG, "../../etc/passwd\x00.jpg")
    assert r.status_code == 201
    assert "/" not in r.json()["original_name"] and "\x00" not in r.json()["original_name"]


def test_size_limit(client, ticket, upload_dir, settings):
    settings.max_upload_mb = 1
    assert up(client, ticket, JPG + b"0" * (1024 * 1024 + 10)).status_code == 413
    assert list(upload_dir.iterdir()) == []
    assert up(client, ticket, JPG).status_code == 201


def test_empty_and_tiny_files(client, ticket, upload_dir):
    assert up(client, ticket, b"").status_code == 415
    assert up(client, ticket, b"\xff\xd8\xff").status_code == 201       # valid signature, tiny but not empty


def test_max_files_per_user(client, ticket, upload_dir):
    for _ in range(3):
        assert up(client, ticket, JPG).status_code == 201
    r = up(client, ticket, JPG)
    assert r.status_code == 409 and "3" in r.json()["detail"]


def test_malware_scan_rejects_and_cleans_up(client, ticket, upload_dir, monkeypatch):
    monkeypatch.setattr("grievance_app.services.attachments.scan_file", lambda path: "infected")
    assert up(client, ticket, JPG).status_code == 422
    assert list(upload_dir.iterdir()) == []


def test_scan_error_also_rejects(client, ticket, upload_dir, monkeypatch):
    monkeypatch.setattr("grievance_app.services.attachments.scan_file", lambda path: "scan_error")
    assert up(client, ticket, JPG).status_code == 422


def test_scan_off_is_recorded(client, ticket, upload_dir):
    assert up(client, ticket, JPG).json()["scan_status"] == "not_scanned"


def test_scan_command_missing_is_an_error(settings, tmp_path, monkeypatch):
    from grievance_app.services.scan import scan_file
    settings.clamav_enabled = True
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert scan_file(str(tmp_path / "x")) == "scan_error"


# ---------- who may upload and download ----------

def test_other_student_cannot_upload_or_download(client, ticket, upload_dir):
    att = up(client, ticket, JPG).json()["id"]
    logout(client); login_as(client, "priya")
    assert up(client, ticket, JPG).status_code == 404
    assert client.get(f"{API}/attachments/{att}").status_code == 404


def test_download_unknown_id_looks_the_same(client, ticket, upload_dir):
    import uuid
    assert client.get(f"{API}/attachments/{uuid.uuid4()}").status_code == 404


def test_handler_can_view_and_add_resolution_photo(client, ticket, upload_dir):
    att = up(client, ticket, JPG).json()["id"]
    logout(client); login_as(client, "caretaker_a")
    assert client.get(f"{API}/attachments/{att}").status_code == 200
    assert up(client, ticket, PNG, "fixed.png", "image/png").status_code == 201
    logout(client); login_as(client, "caretaker_b")
    assert client.get(f"{API}/attachments/{att}").status_code == 404


def test_head_in_chain_can_download(client, ticket, upload_dir):
    att = up(client, ticket, JPG).json()["id"]
    logout(client); login_as(client, "warden")
    assert client.get(f"{API}/attachments/{att}").status_code == 200


def test_confidential_attachment_only_for_reporter_and_officers(client, world, upload_dir):
    login_as(client, "priya")
    tid = new_issue(client, world, category="Library", unit=None, confidential=True).json()["id"]
    att = up(client, tid, PDF, "evidence.pdf", "application/pdf").json()["id"]
    for who in ("admin", "warden", "librarian", "ravi", "cell"):
        logout(client); login_as(client, who)
        assert client.get(f"{API}/attachments/{att}").status_code == 404, who
    logout(client); login_as(client, "officer2")
    assert client.get(f"{API}/attachments/{att}").status_code == 200


def test_no_upload_to_closed_ticket(client, ticket, upload_dir):
    client.post(f"{API}/issues/{ticket}/cancel")
    assert up(client, ticket, JPG).status_code == 409


def test_attachments_listed_on_ticket_detail(client, ticket, upload_dir):
    up(client, ticket, JPG, "front.jpg")
    d = client.get(f"{API}/issues/{ticket}").json()
    assert [a["original_name"] for a in d["attachments"]] == ["front.jpg"]
    assert d["attachments"][0]["uploaded_by_me"] is True
    assert "File added: front.jpg" in [e["text"] for e in d["events"]]


def test_upload_requires_login_and_csrf(client, ticket, upload_dir):
    client.headers.pop("X-CSRF-Token")
    assert up(client, ticket, JPG).status_code == 403
    client.cookies.clear()
    assert up(client, ticket, JPG).status_code == 401
