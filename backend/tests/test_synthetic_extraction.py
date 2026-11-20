"""Gold-standard check of mock-model extraction on the generated synthetic PDFs."""
import importlib.util
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("pdfplumber")

ROOT = Path(__file__).resolve().parents[2] / "synthetic-data"


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("generate_demo_documents", ROOT / "generate_demo_documents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path_factory.mktemp("demo")
    module.build_all(out)
    return out


def _key(name, fact_type, amount, page):
    return (name, fact_type, Decimal(amount), page)


def test_extraction_matches_gold_standard(client, case_id, demo_dir):
    names = sorted(p.name for p in demo_dir.glob("*.pdf"))
    files = [("files", (n, (demo_dir / n).read_bytes(), "application/pdf")) for n in names]
    assert client.post(f"/cases/{case_id}/documents", files=files).status_code == 201

    outcomes = client.post(f"/cases/{case_id}/extract").json()
    assert {o["document"]["filename"]: o["status"] for o in outcomes} == {n: "EXTRACTED" for n in names}

    items = client.get(f"/cases/{case_id}/facts", params={"limit": 500}).json()["items"]
    actual = Counter(
        _key(f["document_filename"], f["fact_type"], f["amount"], f["page_number"])
        for f in items
        if f["amount"] is not None
    )
    gold = json.loads((ROOT / "gold" / "extraction_gold.json").read_text())["facts"]
    expected = Counter(_key(g["document"], g["fact_type"], g["amount"], g["page"]) for g in gold)

    matched = sum((actual & expected).values())
    precision, recall = matched / sum(actual.values()), matched / sum(expected.values())
    assert (precision, recall) == (1.0, 1.0), {
        "missing": list((expected - actual).elements()),
        "unexpected": list((actual - expected).elements()),
    }

    # provenance coverage is complete, including identity facts
    assert all(f["source_text"] and f["page_number"] >= 1 for f in items)


def test_injection_probe_document_is_extracted_normally(client, case_id, demo_dir):
    name = "consolidated_holdings_statement.pdf"
    client.post(
        f"/cases/{case_id}/documents",
        files=[("files", (name, (demo_dir / name).read_bytes(), "application/pdf"))],
    )
    out = client.post(f"/cases/{case_id}/extract").json()[0]
    assert out["status"] == "EXTRACTED"
    items = client.get(f"/cases/{case_id}/facts").json()["items"]
    assert not any("approve" in f["source_text"].lower() for f in items)
