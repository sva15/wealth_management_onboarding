"""Document storage, parsing and OCR ports."""
from dataclasses import dataclass
from typing import Protocol


class DocumentStore(Protocol):
    def save(self, key: str, data: bytes) -> None: ...

    def load(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


class OcrProvider(Protocol):
    def ocr_page(self, pdf_bytes: bytes, page_index: int) -> str:
        """Return recognised text for a zero-based PDF page."""


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str
    used_ocr: bool = False


class DocumentParser(Protocol):
    def parse(self, data: bytes, media_type: str) -> list[ParsedPage]:
        """Return one ParsedPage per page. Raise on unreadable documents."""
