"""End-to-end check of the synthetic PDFs through parsing and classification."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("pdfplumber")

GENERATOR = Path(__file__).resolve().parents[2] / "synthetic-data" / "generate_demo_documents.py"


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("generate_demo_documents", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path_factory.mktemp("demo")
    module.build_all(out)
    return out


def _manifest(demo_dir):
    import json

    return json.loads((demo_dir / "manifest.json").read_text())


def test_all_demo_documents_classify_correctly(client, case_id, demo_dir):
    manifest = _manifest(demo_dir)
    files = [
        ("files", (name, (demo_dir / name).read_bytes(), "application/pdf")) for name in manifest
    ]
    r = client.post(f"/cases/{case_id}/documents", files=files)
    assert r.status_code == 201

    by_name = {x["filename"]: x["document"] for x in r.json()["results"]}
    for name, expected in manifest.items():
        doc = by_name[name]
        assert doc["document_type"] == expected["document_type"], name
        assert doc["page_count"] == expected["pages"], name
        assert doc["processing_status"] == "CLASSIFIED", name


def test_bank_statement_pages_preserve_rows_and_provenance(client, case_id, demo_dir):
    data = (demo_dir / "bank_statement.pdf").read_bytes()
    r = client.post(
        f"/cases/{case_id}/documents", files=[("files", ("bank_statement.pdf", data, "application/pdf"))]
    )
    doc_id = r.json()["results"][0]["document"]["id"]
    pages = client.get(f"/documents/{doc_id}/pages").json()
    assert "Closing balance: INR 1,10,00,000.00" in pages[0]["text"]
    credit_row = next(line for line in pages[1]["text"].splitlines() if "UTR260115001" in line)
    assert "INR 5,04,00,000.00" in credit_row


def test_duplicate_holding_appears_in_two_documents(client, case_id, demo_dir):
    for name in ("portfolio_statement.pdf", "consolidated_holdings_statement.pdf"):
        r = client.post(
            f"/cases/{case_id}/documents",
            files=[("files", (name, (demo_dir / name).read_bytes(), "application/pdf"))],
        )
        doc_id = r.json()["results"][0]["document"]["id"]
        text = client.get(f"/documents/{doc_id}/pages").json()[0]["text"]
        assert "INF000Z01AB1" in text and "11223344/01" in text
