"""Document upload, status, page text and file access endpoints."""
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_context, get_document_service
from app.api.schemas import DocumentOut, DocumentPageOut, UploadOutcomeOut, UploadResponse
from app.domain.enums import Role
from app.services.context import RequestContext, require_role
from app.services.documents import DocumentService

router = APIRouter(tags=["documents"])

MAX_FILES_PER_UPLOAD = 20
_CAN_WRITE = (Role.ANALYST.value, Role.CUSTOMER.value, Role.ADMIN.value)
_STAFF = (Role.ANALYST.value, Role.ADMIN.value)


@router.post("/cases/{case_id}/documents", response_model=UploadResponse)
async def upload_documents(
    case_id: str,
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
    svc: DocumentService = Depends(get_document_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_CAN_WRITE)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(status_code=400, detail=f"At most {MAX_FILES_PER_UPLOAD} files per upload")

    limit = request.app.state.settings.max_upload_mb * 1024 * 1024
    payload = [(f.filename or "document", await f.read(limit + 1)) for f in files]
    outcomes = await run_in_threadpool(svc.upload, case_id, payload)

    results = [
        UploadOutcomeOut(
            filename=o.filename,
            outcome=o.outcome,
            document=DocumentOut.model_validate(o.document) if o.document else None,
            error_code=o.error_code,
            error_message=o.error_message,
        )
        for o in outcomes
    ]
    response.status_code = 201 if any(o.outcome == "ACCEPTED" for o in outcomes) else 200
    return UploadResponse(results=results)


@router.get("/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(case_id: str, svc: DocumentService = Depends(get_document_service)):
    return svc.list_documents(case_id)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, svc: DocumentService = Depends(get_document_service)):
    return svc.get_document(document_id)


@router.post("/documents/{document_id}/process", response_model=DocumentOut)
def reprocess_document(
    document_id: str,
    svc: DocumentService = Depends(get_document_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.process(document_id)


@router.get("/documents/{document_id}/pages", response_model=list[DocumentPageOut])
def get_pages(
    document_id: str,
    svc: DocumentService = Depends(get_document_service),
    ctx: RequestContext = Depends(get_context),
):
    require_role(ctx, *_STAFF)
    return svc.get_pages(document_id)


@router.get("/documents/{document_id}/file")
def get_file(
    document_id: str,
    svc: DocumentService = Depends(get_document_service),
    ctx: RequestContext = Depends(get_context),
):
    """Original files stay private: only staff can open them, and never as executable content."""
    require_role(ctx, *_STAFF)
    doc, data = svc.read_file(document_id)
    return Response(
        content=data,
        media_type=doc.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{doc.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
