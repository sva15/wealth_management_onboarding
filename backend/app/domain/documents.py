"""Upload validation. Pure functions; no I/O."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

ALLOWED_TYPES = {".pdf": "application/pdf", ".txt": "text/plain"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class DocumentValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    extension: str
    media_type: str
    sha256: str
    size_bytes: int


def sanitize_filename(name: str) -> str:
    """Drop any path, replace unsafe characters and bound the length."""
    base = PurePosixPath(name.replace("\\", "/")).name
    path = PurePosixPath(base)
    stem = _UNSAFE.sub("_", path.stem).strip("._-")[:80] or "document"
    ext = _UNSAFE.sub("", path.suffix.lower())[:10]
    return f"{stem}{ext}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_upload(filename: str, data: bytes, max_bytes: int) -> ValidatedUpload:
    safe = sanitize_filename(filename)
    ext = PurePosixPath(safe).suffix
    if not data:
        raise DocumentValidationError("EMPTY_FILE", "The file is empty")
    if len(data) > max_bytes:
        raise DocumentValidationError(
            "FILE_TOO_LARGE", f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit"
        )
    if ext not in ALLOWED_TYPES:
        allowed = ", ".join(sorted(ALLOWED_TYPES))
        raise DocumentValidationError("UNSUPPORTED_TYPE", f"Only {allowed} files are supported")
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise DocumentValidationError("CONTENT_MISMATCH", "The file is not a valid PDF")
    if ext == ".txt":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise DocumentValidationError(
                "CONTENT_MISMATCH", "The file is not valid UTF-8 text"
            ) from None
        if b"\x00" in data:
            raise DocumentValidationError("CONTENT_MISMATCH", "The file is not plain text")
    return ValidatedUpload(
        filename=safe,
        extension=ext,
        media_type=ALLOWED_TYPES[ext],
        sha256=sha256_hex(data),
        size_bytes=len(data),
    )
