from fastapi.testclient import TestClient

from app.main import create_app

BANK_TEXT = (
    "ACCOUNT STATEMENT\nOpening balance: INR 5,00,000.00\n"
    "Closing balance: INR 1,10,00,000.00\nNarration IFSC FIBL0000123\n\f"
    "Page two: RTGS CR ORBIT CAPITAL INR 5,04,00,000.00"
)


def _upload(client, case_id, *files, headers=None):
    payload = [("files", (name, data, "application/octet-stream")) for name, data in files]
    return client.post(f"/cases/{case_id}/documents", files=payload, headers=headers or {})


def test_upload_classifies_and_stores_pages(client, case_id):
    r = _upload(client, case_id, ("scan001.txt", BANK_TEXT.encode()))
    assert r.status_code == 201
    result = r.json()["results"][0]
    doc = result["document"]
    assert result["outcome"] == "ACCEPTED"
    assert doc["document_type"] == "BANK_STATEMENT"
    assert doc["processing_status"] == "CLASSIFIED"
    assert doc["page_count"] == 2 and len(doc["sha256"]) == 64

    pages = client.get(f"/documents/{doc['id']}/pages").json()
    assert [p["page_number"] for p in pages] == [1, 2]
    assert "5,04,00,000.00" in pages[1]["text"]

    assert client.get(f"/cases/{case_id}").json()["status"] == "PROCESSING"
    actions = [e["action"] for e in client.get(f"/cases/{case_id}/audit").json()["items"]]
    assert "document.uploaded" in actions and "document.processed" in actions


def test_duplicate_upload_is_detected_and_not_stored_twice(client, case_id):
    _upload(client, case_id, ("a.txt", BANK_TEXT.encode()))
    r = _upload(client, case_id, ("renamed.txt", BANK_TEXT.encode()))
    assert r.status_code == 200
    assert r.json()["results"][0]["outcome"] == "DUPLICATE"
    assert len(client.get(f"/cases/{case_id}/documents").json()) == 1


def test_rejected_files_report_clear_errors(client, case_id):
    r = _upload(client, case_id, ("virus.exe", b"MZ"), ("empty.txt", b""))
    assert r.status_code == 200
    codes = {x["filename"]: x["error_code"] for x in r.json()["results"]}
    assert codes == {"virus.exe": "UNSUPPORTED_TYPE", "empty.txt": "EMPTY_FILE"}
    assert client.get(f"/cases/{case_id}/documents").json() == []


def test_oversized_file_rejected(settings, tmp_path):
    small = settings.model_copy(update={"max_upload_mb": 1})
    with TestClient(create_app(small)) as c:
        cust = c.post("/customers", json={"full_name": "X"}).json()
        case = c.post("/cases", json={"customer_id": cust["id"]}).json()["id"]
        r = _upload(c, case, ("big.txt", b"a" * (1024 * 1024 + 1)))
    assert r.json()["results"][0]["error_code"] == "FILE_TOO_LARGE"


def test_unknown_document_routes_to_review(client, case_id):
    r = _upload(client, case_id, ("notes.txt", b"hello world"))
    doc = r.json()["results"][0]["document"]
    assert doc["document_type"] == "UNKNOWN"
    assert doc["processing_status"] == "REQUIRES_REVIEW"
    assert doc["error_message"]
    assert client.get(f"/cases/{case_id}").json()["status"] == "REQUIRES_REVIEW"


def test_reprocessing_is_idempotent(client, case_id):
    doc = _upload(client, case_id, ("scan.txt", BANK_TEXT.encode())).json()["results"][0]["document"]
    for _ in range(2):
        assert client.post(f"/documents/{doc['id']}/process").status_code == 200
    assert len(client.get(f"/documents/{doc['id']}/pages").json()) == 2


def test_original_file_access_is_staff_only(client, case_id):
    doc = _upload(client, case_id, ("scan.txt", BANK_TEXT.encode())).json()["results"][0]["document"]
    ok = client.get(f"/documents/{doc['id']}/file")
    assert ok.status_code == 200 and ok.content == BANK_TEXT.encode()
    assert ok.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get(f"/documents/{doc['id']}/file", headers={"X-Actor-Role": "customer"}).status_code == 403
    assert client.get(f"/documents/{doc['id']}/pages", headers={"X-Actor-Role": "customer"}).status_code == 403


def test_unknown_case_and_document(client):
    assert _upload(client, "missing", ("a.txt", b"x")).status_code == 404
    assert client.get("/documents/missing").status_code == 404
