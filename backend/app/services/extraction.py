"""Structured fact extraction: model call, validation, one repair attempt, grounding, persistence."""
from dataclasses import dataclass, field

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.persistence.models import (
    DocumentPageRow,
    DocumentRow,
    ExtractedFactRow,
    ExtractionDiagnosticRow,
    OnboardingCaseRow,
)
from app.domain.enums import ExtractionMethod, ProcessingStatus, VerificationStatus
from app.extraction import tasks
from app.extraction.grounding import FactBuilder, FactDraft
from app.extraction.parsing import ExtractionParseError, parse_model_output
from app.extraction.prompts import build_repair_request, build_request
from app.extraction.registry import EXTRACTORS, ExtractorSpec
from app.ports.llm import LlmClient, LlmError, LlmRequest, LlmResponse
from app.services.audit import AuditService
from app.services.case_status import refresh_case_status
from app.services.context import RequestContext, authorize_case_access
from app.services.errors import ConflictError, NotFoundError

log = structlog.get_logger()


@dataclass
class ExtractionOutcome:
    document: DocumentRow
    status: str
    facts_created: int = 0
    facts_total: int = 0
    issues: list[str] = field(default_factory=list)


class ExtractionService:
    def __init__(
        self,
        session: Session,
        ctx: RequestContext,
        llm: LlmClient,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._s = session
        self._ctx = ctx
        self._llm = llm
        self._threshold = confidence_threshold
        self._audit = AuditService(session, ctx)

    # --- public API -------------------------------------------------------
    def extract_document(self, document_id: str, workflow_run_id: str | None = None) -> ExtractionOutcome:
        doc = self._document(document_id)
        spec = EXTRACTORS.get(doc.document_type or "")
        if spec is None:
            raise ConflictError("This document type is not supported for extraction")
        pages = {
            p.page_number: p.text
            for p in self._s.scalars(
                select(DocumentPageRow).where(DocumentPageRow.document_id == doc.id)
            )
        }
        if not any(pages.values()):
            raise ConflictError("The document has no extractable text")

        previous_status = doc.processing_status
        request = build_request(spec.task, spec.schema, pages, tasks.PROMPT_VERSION)

        try:
            extraction = self._invoke_validated(doc, spec, request, workflow_run_id)
        except LlmError as exc:
            doc.processing_status = ProcessingStatus.FAILED.value
            doc.error_message = f"Model call failed ({exc.code}). Retry extraction later."
            return self._finish(doc, previous_status, "extraction.failed", ExtractionOutcome(doc, "FAILED"))
        except ExtractionParseError:
            doc.processing_status = ProcessingStatus.REQUIRES_REVIEW.value
            doc.error_message = "The model output was invalid after one repair attempt; manual review needed."
            return self._finish(
                doc,
                previous_status,
                "extraction.invalid_output",
                ExtractionOutcome(doc, "REQUIRES_REVIEW", issues=["Invalid model output after repair"]),
            )

        builder = FactBuilder(pages)
        spec.flatten(extraction, builder)
        created = self._persist(doc, builder.drafts, workflow_run_id)

        low_confidence = sum(d.confidence < self._threshold for d in builder.drafts)
        problems = []
        if builder.issues:
            problems.append(f"{len(builder.issues)} item(s) failed source verification and were not saved.")
            self._diagnostic(
                doc, request, tasks.PROMPT_VERSION, "validation", "GROUNDING_FAILED",
                "; ".join(builder.issues[:30]), None,
            )
        if low_confidence:
            problems.append(f"{low_confidence} fact(s) have low extraction confidence.")
        if not builder.drafts:
            problems.append("No facts could be extracted.")

        if problems:
            doc.processing_status = ProcessingStatus.REQUIRES_REVIEW.value
            doc.error_message = " ".join(problems)
        else:
            doc.processing_status = ProcessingStatus.EXTRACTED.value
            doc.error_message = None

        total = self._s.scalar(
            select(func.count())
            .select_from(ExtractedFactRow)
            .where(
                ExtractedFactRow.document_id == doc.id,
                ExtractedFactRow.verification_status != VerificationStatus.SUPERSEDED.value,
            )
        )
        return self._finish(
            doc,
            previous_status,
            "extraction.completed",
            ExtractionOutcome(doc, doc.processing_status, created, total or 0, builder.issues),
            workflow_run_id,
        )

    def extract_case(self, case_id: str) -> list[ExtractionOutcome]:
        self._case(case_id)
        docs = self._s.scalars(
            select(DocumentRow)
            .where(
                DocumentRow.case_id == case_id,
                DocumentRow.processing_status == ProcessingStatus.CLASSIFIED.value,
            )
            .order_by(DocumentRow.uploaded_at, DocumentRow.id)
        ).all()
        return [self.extract_document(d.id) for d in docs if d.document_type in EXTRACTORS]

    def list_facts(
        self,
        case_id: str,
        limit: int,
        offset: int,
        document_id: str | None = None,
        fact_type: str | None = None,
        include_superseded: bool = False,
    ) -> tuple[list[tuple[ExtractedFactRow, str]], int]:
        self._case(case_id)
        query = (
            select(ExtractedFactRow, DocumentRow.filename)
            .join(DocumentRow, DocumentRow.id == ExtractedFactRow.document_id)
            .where(ExtractedFactRow.case_id == case_id)
        )
        if document_id:
            query = query.where(ExtractedFactRow.document_id == document_id)
        if fact_type:
            query = query.where(ExtractedFactRow.fact_type == fact_type)
        if not include_superseded:
            query = query.where(
                ExtractedFactRow.verification_status != VerificationStatus.SUPERSEDED.value
            )
        total = self._s.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._s.execute(
            query.order_by(DocumentRow.filename, ExtractedFactRow.page_number, ExtractedFactRow.created_at, ExtractedFactRow.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return [(fact, name) for fact, name in rows], total

    def list_diagnostics(self, document_id: str) -> list[ExtractionDiagnosticRow]:
        doc = self._document(document_id)
        return list(
            self._s.scalars(
                select(ExtractionDiagnosticRow)
                .where(ExtractionDiagnosticRow.document_id == doc.id)
                .order_by(ExtractionDiagnosticRow.created_at, ExtractionDiagnosticRow.id)
            )
        )

    # --- model interaction ------------------------------------------------
    def _invoke_validated(
        self, doc: DocumentRow, spec: ExtractorSpec, request: LlmRequest, run_id: str | None
    ):
        response = self._call(doc, request, run_id)
        try:
            return parse_model_output(spec.schema, response.text)
        except ExtractionParseError as first:
            self._diagnostic(
                doc, request, tasks.PROMPT_VERSION, "initial", first.error_type, first.summary,
                response.text, response.model_id,
            )
            repair = build_repair_request(request, response.text, first.summary)

        retry = self._call(doc, repair, run_id)
        try:
            return parse_model_output(spec.schema, retry.text)
        except ExtractionParseError as second:
            self._diagnostic(
                doc, repair, tasks.PROMPT_VERSION, "repair", second.error_type, second.summary,
                retry.text, retry.model_id,
            )
            raise

    def _call(self, doc: DocumentRow, request: LlmRequest, run_id: str | None) -> LlmResponse:
        response = self._llm.invoke(request)
        self._audit.record(
            action="extraction.model_invoked",
            entity_type="document",
            entity_id=doc.id,
            case_id=doc.case_id,
            workflow_run_id=run_id,
            model_version=response.model_id,
            new={
                "task": request.task,
                "prompt_version": request.prompt_version,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
            },
        )
        return response

    def _diagnostic(
        self,
        doc: DocumentRow,
        request: LlmRequest,
        prompt_version: str,
        stage: str,
        error_type: str,
        summary: str,
        raw: str | None,
        model_id: str | None = None,
    ) -> None:
        self._s.add(
            ExtractionDiagnosticRow(
                case_id=doc.case_id,
                document_id=doc.id,
                task=request.task,
                prompt_version=prompt_version,
                model_id=model_id or self._llm.model_id,
                stage=stage,
                error_type=error_type,
                error_summary=summary,
                raw_response=raw,
            )
        )

    # --- persistence ------------------------------------------------------
    def _persist(self, doc: DocumentRow, drafts: list[FactDraft], run_id: str | None) -> int:
        """Idempotent: identical facts are kept, vanished model facts are superseded, edits are untouched."""
        existing = {
            f.idempotency_key: f
            for f in self._s.scalars(select(ExtractedFactRow).where(ExtractedFactRow.document_id == doc.id))
        }
        seen: set[str] = set()
        created = 0
        for draft in drafts:
            key = draft.idempotency_key(doc.id)
            seen.add(key)
            current = existing.get(key)
            if current is not None:
                if current.verification_status == VerificationStatus.SUPERSEDED.value:
                    current.verification_status = VerificationStatus.EXTRACTED.value
                continue
            fact = ExtractedFactRow(
                case_id=doc.case_id,
                document_id=doc.id,
                page_number=draft.page,
                fact_type=draft.fact_type,
                amount=draft.amount,
                normalized_value=draft.normalized or None,
                original_value=draft.original_value,
                currency=draft.currency,
                effective_date=draft.effective_date,
                source_text=draft.source_text,
                extraction_method=ExtractionMethod.LLM.value,
                confidence=draft.confidence,
                verification_status=VerificationStatus.EXTRACTED.value,
                model_id=self._llm.model_id,
                prompt_version=tasks.PROMPT_VERSION,
                idempotency_key=key,
            )
            self._s.add(fact)
            self._s.flush()
            created += 1
            self._audit.record(
                action="fact.created",
                entity_type="fact",
                entity_id=fact.id,
                case_id=doc.case_id,
                workflow_run_id=run_id,
                model_version=self._llm.model_id,
                new={"fact_type": fact.fact_type, "page": fact.page_number},
            )

        for key, fact in existing.items():
            if (
                key not in seen
                and fact.extraction_method == ExtractionMethod.LLM.value
                and fact.verification_status == VerificationStatus.EXTRACTED.value
            ):
                fact.verification_status = VerificationStatus.SUPERSEDED.value
                self._audit.record(
                    action="fact.superseded",
                    entity_type="fact",
                    entity_id=fact.id,
                    case_id=doc.case_id,
                    workflow_run_id=run_id,
                    previous={"verification_status": VerificationStatus.EXTRACTED.value},
                    new={"verification_status": VerificationStatus.SUPERSEDED.value},
                    reason="Not reproduced by a later extraction run",
                )
        self._s.flush()
        return created

    def _finish(
        self,
        doc: DocumentRow,
        previous_status: str,
        action: str,
        outcome: ExtractionOutcome,
        run_id: str | None = None,
    ) -> ExtractionOutcome:
        outcome.status = doc.processing_status
        self._audit.record(
            action=action,
            entity_type="document",
            entity_id=doc.id,
            case_id=doc.case_id,
            workflow_run_id=run_id,
            previous={"processing_status": previous_status},
            new={
                "processing_status": doc.processing_status,
                "facts_created": outcome.facts_created,
                "issue_count": len(outcome.issues),
            },
        )
        self._s.flush()
        refresh_case_status(self._s, self._audit, doc.case_id)
        self._s.commit()
        return outcome

    # --- lookups ----------------------------------------------------------
    def _case(self, case_id: str) -> OnboardingCaseRow:
        authorize_case_access(self._ctx, case_id)
        case = self._s.get(OnboardingCaseRow, case_id)
        if case is None:
            raise NotFoundError("Case not found")
        return case

    def _document(self, document_id: str) -> DocumentRow:
        doc = self._s.get(DocumentRow, document_id)
        if doc is None:
            raise NotFoundError("Document not found")
        authorize_case_access(self._ctx, doc.case_id)
        return doc
