"""Parsing of PDFs and plain text, with optional OCR for pages that have no text layer."""
import io

from app.ports.documents import OcrProvider, ParsedPage

MAX_PAGES = 200


class TesseractOcrProvider:
    """Open-source OCR (Tesseract). Needs `pip install -r requirements-ocr.txt` and the Tesseract binary."""

    def ocr_page(self, pdf_bytes: bytes, page_index: int) -> str:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            pix = doc[page_index].get_pixmap(dpi=200)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(image)


class LocalDocumentParser:
    def __init__(self, ocr: OcrProvider | None = None) -> None:
        self._ocr = ocr

    def parse(self, data: bytes, media_type: str) -> list[ParsedPage]:
        if media_type == "text/plain":
            return self._parse_text(data)
        if media_type == "application/pdf":
            return self._parse_pdf(data)
        raise ValueError(f"Unsupported media type: {media_type}")

    @staticmethod
    def _parse_text(data: bytes) -> list[ParsedPage]:
        # A form feed separates pages in plain-text documents.
        chunks = data.decode("utf-8").split("\f")
        return [ParsedPage(i + 1, chunk.strip()) for i, chunk in enumerate(chunks)]

    def _parse_pdf(self, data: bytes) -> list[ParsedPage]:
        import pdfplumber

        pages: list[ParsedPage] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise ValueError(f"Document exceeds {MAX_PAGES} pages")
            for index, page in enumerate(pdf.pages):
                # pdfplumber keeps table rows on one line, which the extractors rely on.
                text = (page.extract_text() or "").strip()
                used_ocr = False
                if not text and self._ocr is not None:
                    text = self._ocr.ocr_page(data, index).strip()
                    used_ocr = True
                pages.append(ParsedPage(index + 1, text, used_ocr))
        return pages


def build_parser(processor_mode: str) -> LocalDocumentParser:
    ocr = TesseractOcrProvider() if processor_mode == "local_ocr" else None
    return LocalDocumentParser(ocr)
