"""Split the lines of a label PDF into the sections of the full prescribing information.
Rules come from the PyMuPDF spike (docs/agent-log.md, 2026-11-20)."""

import re
from collections.abc import Sequence

from app.domain.entities import LabelSection, PdfLine

BODY_START = "FULL PRESCRIBING INFORMATION"
BOXED_WARNING = "BW"
_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\s+(\S.*)$")
_MAX_TOP_LEVEL = 17
# A guide title whose next letter is lower case is section 17 text ("Patient Information about").
_END_TITLES = ("MEDICATION GUIDE", "PATIENT INFORMATION", "INSTRUCTIONS FOR USE")
_END_PREFIXES = ("PACKAGE LABEL", "PRINCIPAL DISPLAY PANEL")
# A heading line that ends like this continues on the next bold line.
_CONTINUES = (",", " and", " of", " with", " in", " for", " to", " or", "-", "/")


class LabelFormatError(ValueError):
    pass


def _heading(line: PdfLine, last_top: int) -> tuple[str, str] | None:
    """A bold numbered line whose title starts upper case and whose number does not go back.
    The last two rules reject bold table cells such as "10 mg" (phase 2 ingest report)."""
    match = _HEADING.match(line.text) if line.bold else None
    if not match or not match[2][0].isupper():
        return None
    top = int(match[1].split(".")[0])
    if not last_top <= top <= _MAX_TOP_LEVEL:
        return None
    return match[1], match[2].rstrip("*").strip()


def _is_end(line: PdfLine) -> bool:
    text = line.text.strip()
    return line.text.startswith("Revised:") or (
        line.bold and (_is_guide_title(text) or text.upper().startswith(_END_PREFIXES))
    )


def _is_guide_title(text: str) -> bool:
    title = next((t for t in _END_TITLES if text.upper().startswith(t)), None)
    letters = [c for c in text[len(title) :] if c.isalpha()] if title else []
    return title is not None and not (letters and letters[0].islower())


def split_sections(lines: Sequence[PdfLine]) -> list[LabelSection]:
    starts = [i for i, line in enumerate(lines) if line.text.strip() == BODY_START]
    if not starts:
        raise LabelFormatError("The label has no FULL PRESCRIBING INFORMATION section")

    sections: list[LabelSection] = []
    number: str | None = None
    title = ""
    content: list[PdfLine] = []
    in_title = False

    def close() -> None:
        if number is not None:
            sections.append(LabelSection(number=number, title=title, lines=tuple(content)))

    for line in lines[starts[0] + 1 :]:
        if number is not None and _is_end(line):
            break
        last_top = int(number.split(".")[0]) if number and number != BOXED_WARNING else 1
        heading = _heading(line, last_top)
        if heading:
            close()
            (number, title), content, in_title = heading, [], True
            continue
        if number is None and line.bold and line.text.startswith("WARNING:"):
            number, title, content, in_title = BOXED_WARNING, line.text, [], True
            continue
        if number is None:
            continue  # notes between the body start and the first section
        if in_title and line.bold and _title_continues(number, title, line):
            title = f"{title} {line.text}"
            continue
        in_title = False
        content.append(line)
    close()
    return sections


def _title_continues(number: str, title: str, line: PdfLine) -> bool:
    if number == BOXED_WARNING:
        # The boxed warning title is the upper-case heading; its body is bold sentence text.
        letters = [c for c in line.text if c.isalpha()]
        return sum(c.isupper() for c in letters) > 0.6 * max(len(letters), 1)
    return title.endswith(_CONTINUES)
