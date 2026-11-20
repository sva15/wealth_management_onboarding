"""Page-marked text blocks shared by prompt building, grounding checks and the mock client."""
import re

_MARKER = re.compile(r"^\[\[PAGE (\d+)\]\]\s*$", re.MULTILINE)


def _neutralise(text: str) -> str:
    # Stop untrusted text from forging page markers or closing the prompt's data delimiter.
    return text.replace("[[PAGE", "[ [PAGE").replace("</document>", "< /document>")


def format_pages(pages: dict[int, str]) -> str:
    return "\n".join(f"[[PAGE {n}]]\n{_neutralise(pages[n])}\n" for n in sorted(pages))


def split_pages(text: str) -> dict[int, str]:
    marks = list(_MARKER.finditer(text))
    pages: dict[int, str] = {}
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        pages[int(mark.group(1))] = text[mark.end() : end].strip()
    return pages
