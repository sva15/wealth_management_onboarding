"""Document upload, parsing and classification use cases."""
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.persistence.models import (
    DocumentPageRow,
    DocumentRow,
    OnboardingCaseRow,
)
from app.domain.classification import ClassificationResult, classify_document
from app.domain.documents import DocumentValidationError, validate_upload
from app.domain.enums import ProcessingStatus
from app.extraction.llm_classification import classify_with_llm
from app.ports.documents import DocumentParser, DocumentStore
from app.ports.llm import LlmClient
from app.services.audit import AuditService
from app.services.case_status import refresh_case_status
from app.services.context import RequestContext, authorize_case_access
from app.services.errors import NotFoundError

log = structlog.get_logger()

# Text used for classification is bounded; the first pages carry the identifying title and headers.
_CLASSIFY_PAGES = 2


@dataclass
class UploadOutcome:
    filename: str
    outcome: str  # ACCEPTED | DUPLICATE | REJECTED
    document: DocumentRow | None = None
    error_code: str | None = None
    error_message: str | None = None


class DocumentService:
    def __init__(
        self,
        session: Session,
        ctx: RequestContext,
        store: DocumentStore,
        parser: DocumentParser,
        max_upload_bytes: int,
        review_threshold: float,
        llm: LlmClient | None = None,
    ) -> None:
        self._s = session
        self._ctx = ctx
        self._store = store
        self._parser = parser
        self._max_bytes = max_upload_bytes
        self._threshold = review_threshold
        self._llm = llm
        self._audit = AuditService(session, ctx)

    # --- upload ----------------------------------------------------------
    def _case(self, case_id: str) -> OnboardingCaseRow:
        authorize_case_access(self._ctx, case_id)
        case = self._s.get(OnboardingCaseRow, case_id)
        if case is None:
            raise NotFoundError("Case not found")
        return case

    def upload(self, case_id: str, files: list[tuple[str, bytes]]) -> list[UploadOutcome]:
        self._case(case_id)
        return [self._upload_one(case_id, name, data) for name, data in files]

    def _upload_one(self, case_id: str, name: str, data: bytes) -> UploadOutcome:
        try:
            valid = validate_upload(name, data, self._max_bytes)
        except DocumentValidationError as exc:
            self._audit.record(
                action="document.upload_rejected",
                entity_type="case",
                entity_id=case_id,
                case_id=case_id,
                new={"error_code": exc.code},
            )
            self._s.commit()
            return UploadOutcome(
                filename=name[-120:], outcome="REJECTED", error_code=exc.code, error_message=exc.message
            )

        existing = self._find_by_hash(case_id, valid.sha256)
        if existing is not None:
            return self._duplicate(case_id, existing)

        storage_key = f"{case_id}/{valid.sha256}{valid.extension}"
        self._store.save(storage_key, data)
        doc = DocumentRow(
            case_id=case_id,
            filename=valid.filename,
            sha256=valid.sha256,
            size_bytes=valid.size_bytes,
            media_type=valid.media_type,
            storage_key=storage_key,
            processing_status=ProcessingStatus.UPLOADED.value,
        )
        self._s.add(doc)
        try:
            self._s.flush()
        except IntegrityError:
            # A concurrent upload of the same bytes won the race.
            self._s.rollback()
            existing = self._find_by_hash(case_id, valid.sha256)
            if existing is None:
                raise
            return self._duplicate(case_id, existing)

        self._audit.record(
            action="document.uploaded",
            entity_type="document",
            entity_id=doc.id,
            case_id=case_id,
            new={"filename": doc.filename, "sha256": doc.sha256, "size_bytes": doc.size_bytes},
        )
        self._s.commit()
        self.process(doc.id)
        return UploadOutcome(filename=doc.filename, outcome="ACCEPTED", document=doc)

    def _duplicate(self, case_id: str, existing: DocumentRow) -> UploadOutcome:
        self._audit.record(
            action="document.duplicate_upload_detected",
            entity_type="document",
            entity_id=existing.id,
            case_id=case_id,
            new={"sha256": existing.sha256},
        )
        self._s.commit()
        return UploadOutcome(
            filename=existing.filename,
            outcome="DUPLICATE",
            document=existing,
            error_code="DUPLICATE_UPLOAD",
            error_message="This exact file was already uploaded to the case",
        )

    def _find_by_hash(self, case_id: str, sha256: str) -> DocumentRow | None:
        return self._s.scalars(
            select(DocumentRow).where(DocumentRow.case_id == case_id, DocumentRow.sha256 == sha256)
        ).first()

    # --- processing (parse + classify). Idempotent: pages are replaced on every run. ---
    def process(self, document_id: str) -> DocumentRow:
        doc = self.get_document(document_id)
        previous = doc.processing_status
        self._s.execute(delete(DocumentPageRow).where(DocumentPageRow.document_id == doc.id))

        try:
            pages = self._parser.parse(self._store.load(doc.storage_key), doc.media_type)
        except Exception as exc:
            # Only the exception type is stored: messages may contain document content.
            log.warning("document_parse_failed", document_id=doc.id, error_type=type(exc).__name__)
            doc.processing_status = ProcessingStatus.FAILED.value
            doc.error_message = f"Parsing failed ({type(exc).__name__}). Re-upload or process again."
            doc.document_type = None
            doc.classification_confidence = None
            doc.classification_explanation = None
            doc.page_count = None
            self._finish(doc, previous, "document.processing_failed")
            return doc

        for page in pages:
            self._s.add(
                DocumentPageRow(document_id=doc.id, page_number=page.page_number, text=page.text)
            )
        doc.page_count = len(pages)

        empty_pages = [p.page_number for p in pages if not p.text]
        sample = "\n".join(p.text for p in pages[:_CLASSIFY_PAGES])
        result = classify_document(doc.filename, sample, self._threshold)
        if result.requires_human_review and self._llm is not None:
            result = self._classify_with_llm(doc, sample, result)
        doc.document_type = result.document_type.value
        doc.classification_confidence = result.confidence
        doc.classification_explanation = result.explanation

        problems = []
        if empty_pages:
            problems.append(
                f"No extractable text on page(s) {', '.join(map(str, empty_pages))}; OCR may be required."
            )
        if result.requires_human_review:
            problems.append("Document type could not be determined confidently.")
        if problems:
            doc.processing_status = ProcessingStatus.REQUIRES_REVIEW.value
            doc.error_message = " ".join(problems)
        else:
            doc.processing_status = ProcessingStatus.CLASSIFIED.value
            doc.error_message = None

        self._finish(doc, previous, "document.processed")
        return doc

    def _finish(self, doc: DocumentRow, previous_status: str, action: str) -> None:
        self._audit.record(
            action=action,
            entity_type="document",
            entity_id=doc.id,
            case_id=doc.case_id,
            previous={"processing_status": previous_status},
            new={
                "processing_status": doc.processing_status,
                "document_type": doc.document_type,
                "classification_confidence": doc.classification_confidence,
                "page_count": doc.page_count,
            },
        )
        self._s.flush()
        refresh_case_status(self._s, self._audit, doc.case_id)
        self._s.commit()

    def _classify_with_llm(
        self, doc: DocumentRow, sample: str, fallback: ClassificationResult
    ) -> ClassificationResult:
        outcome = classify_with_llm(self._llm, sample)
        if outcome is None:
            return fallback
        result, response = outcome
        self._audit.record(
            action="classification.model_invoked",
            entity_type="document",
            entity_id=doc.id,
            case_id=doc.case_id,
            model_version=response.model_id,
            new={
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
            },
        )
        return fallback if result.requires_human_review else result

    # --- queries ---------------------------------------------------------
    def get_document(self, document_id: str) -> DocumentRow:
        doc = self._s.get(DocumentRow, document_id)
        if doc is None:
            raise NotFoundError("Document not found")
        authorize_case_access(self._ctx, doc.case_id)
        return doc

    def list_documents(self, case_id: str) -> list[DocumentRow]:
        self._case(case_id)
        return list(
            self._s.scalars(
                select(DocumentRow)
                .where(DocumentRow.case_id == case_id)
                .order_by(DocumentRow.uploaded_at, DocumentRow.id)
            )
        )

    def get_pages(self, document_id: str) -> list[DocumentPageRow]:
        doc = self.get_document(document_id)
        return list(
            self._s.scalars(
                select(DocumentPageRow)
                .where(DocumentPageRow.document_id == doc.id)
                .order_by(DocumentPageRow.page_number)
            )
        )

    def read_file(self, document_id: str) -> tuple[DocumentRow, bytes]:
        doc = self.get_document(document_id)
        return doc, self._store.load(doc.storage_key)
