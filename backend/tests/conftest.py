from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        graph_backend="memory",
        document_storage_dir=str(tmp_path / "docs"),
        reconciliation_as_of_date=date(2026, 4, 15),  # pinned so the 31 March 2026 demo documents stay fresh
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def create_case(client) -> str:
    cust = client.post("/customers", json={"full_name": "Test Person", "pan": "ABCDE1234F"})
    case = client.post("/cases", json={"customer_id": cust.json()["id"]})
    return case.json()["id"]


@pytest.fixture
def case_id(client) -> str:
    return create_case(client)
