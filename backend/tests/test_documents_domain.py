import pytest

from app.domain.case_status import derive_case_status
from app.domain.classification import classify_document
from app.domain.documents import DocumentValidationError, sanitize_filename, validate_upload
from app.domain.enums import DocumentType


def test_sanitize_filename_removes_paths_and_unsafe_characters():
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("C:\\Users\\x\\Bank Statement (1).PDF") == "Bank_Statement_1.pdf"
    assert sanitize_filename("...") == "document"


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("a.pdf", b"", "EMPTY_FILE"),
        ("a.exe", b"MZ...", "UNSUPPORTED_TYPE"),
        ("a.pdf", b"not a pdf", "CONTENT_MISMATCH"),
        ("a.txt", b"\xff\xfe\x00bad", "CONTENT_MISMATCH"),
        ("a.txt", b"x" * 11, "FILE_TOO_LARGE"),
    ],
)
def test_validate_upload_rejections(name, data, code):
    with pytest.raises(DocumentValidationError) as exc:
        validate_upload(name, data, max_bytes=10)
    assert exc.value.code == code


def test_validate_upload_accepts_and_hashes():
    v = validate_upload("Bank.PDF", b"%PDF-1.4 content", max_bytes=1000)
    assert v.filename == "Bank.pdf" and v.media_type == "application/pdf"
    assert len(v.sha256) == 64


def test_classification_from_content_without_filename_hint():
    text = "ACCOUNT STATEMENT\nOpening balance INR 1\nClosing balance INR 2\nNarration IFSC"
    result = classify_document("scan001.pdf", text)
    assert result.document_type == DocumentType.BANK_STATEMENT
    assert not result.requires_human_review


def test_loan_statement_is_not_mistaken_for_bank_statement():
    text = "LOAN ACCOUNT STATEMENT Outstanding principal Sanctioned amount EMI Interest rate"
    assert classify_document("loan_statement.pdf", text).document_type == DocumentType.LIABILITY_STATEMENT


def test_unknown_document_requires_review():
    result = classify_document("notes.pdf", "hello world")
    assert result.document_type == DocumentType.UNKNOWN
    assert result.requires_human_review and result.confidence == 0.0


def test_case_status_derivation():
    assert derive_case_status("AWAITING_DOCUMENTS", []) == "AWAITING_DOCUMENTS"
    assert derive_case_status("AWAITING_DOCUMENTS", ["CLASSIFIED"]) == "PROCESSING"
    assert derive_case_status("PROCESSING", ["CLASSIFIED", "REQUIRES_REVIEW"]) == "REQUIRES_REVIEW"
    assert derive_case_status("PROCESSING", ["REQUIRES_REVIEW", "FAILED"]) == "EXTRACTION_FAILED"
    # states owned by later workflow stages are never overwritten
    assert derive_case_status("AWAITING_CUSTOMER_EVIDENCE", ["FAILED"]) == "AWAITING_CUSTOMER_EVIDENCE"
