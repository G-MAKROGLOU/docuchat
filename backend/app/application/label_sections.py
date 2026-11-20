"""Split the lines of a label PDF into the sections of the full prescribing information.
Rules come from the PyMuPDF spike (docs/agent-log.md, 2026-11-20)."""

import logging
import re
from collections.abc import Sequence

from app.domain.entities import LabelSection, PdfLine

BODY_START = "FULL PRESCRIBING INFORMATION"
BOXED_WARNING = "BW"
_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+(\S.*)$")  # "3 TITLE" or "3. TITLE"
_WORD = re.compile(r"[A-Z]+")
# A title cut at the end of a line keeps a partial last word of at least this many letters.
_MIN_PARTIAL_WORD = 4
_MIN_SHORTENED_WORDS = 2
# Top-level section titles fixed by the PLR format (21 CFR 201.57(c)).
_TOP_LEVEL_TITLES = {
    1: "INDICATIONS AND USAGE",
    2: "DOSAGE AND ADMINISTRATION",
    3: "DOSAGE FORMS AND STRENGTHS",
    4: "CONTRAINDICATIONS",
    5: "WARNINGS AND PRECAUTIONS",
    6: "ADVERSE REACTIONS",
    7: "DRUG INTERACTIONS",
    8: "USE IN SPECIFIC POPULATIONS",
    9: "DRUG ABUSE AND DEPENDENCE",
    10: "OVERDOSAGE",
    11: "DESCRIPTION",
    12: "CLINICAL PHARMACOLOGY",
    13: "NONCLINICAL TOXICOLOGY",
    14: "CLINICAL STUDIES",
    15: "REFERENCES",
    16: "HOW SUPPLIED/STORAGE AND HANDLING",
    17: "PATIENT COUNSELING INFORMATION",
}
# A guide title whose next letter is lower case is section 17 text ("Patient Information about").
_END_TITLES = ("MEDICATION GUIDE", "PATIENT INFORMATION", "INSTRUCTIONS FOR USE")
_END_PREFIXES = ("PACKAGE LABEL", "PRINCIPAL DISPLAY PANEL")
# A heading line that ends like this continues on the next bold line.
_CONTINUES = (",", " and", " of", " with", " in", " for", " to", " or", "-", "/")


logger = logging.getLogger(__name__)


class LabelFormatError(ValueError):
    pass


def _heading(line: PdfLine, current: int | None) -> tuple[str, str] | None:
    """A bold numbered line whose title starts upper case and whose number does not go back.
    These rules and the standard top-level titles reject bold table cells ("10 mg", "6 Weeks")."""
    match = _HEADING.match(line.text) if line.bold else None
    if not match or not match[2][0].isupper():
        return None
    top = int(match[1].split(".")[0])
    if not (current or 1) <= top <= len(_TOP_LEVEL_TITLES):
        return None
    if "." in match[1]:
        # A subsection opens only inside its own section; a jump ahead is a table cell.
        return (match[1], match[2].rstrip("*").strip()) if current in {None, top} else None
    if not _is_standard_title(top, match[2]):
        logger.info("top-level heading rejected", extra={"line": line.text})
        return None
    return match[1], match[2].rstrip("*").strip()


def _words(text: str) -> list[str]:
    return _WORD.findall(text.upper().replace("-", ""))


def _is_standard_title(top: int, title: str) -> bool:
    line, standard = _words(title), _words(_TOP_LEVEL_TITLES[top])
    n = len(line)
    if not line or line[: len(standard)] == standard:
        return bool(line)
    # The start of the title, cut at the end of the line, maybe inside its last word.
    if n <= len(standard) and line[:-1] == standard[: n - 1]:
        last, expected = line[-1], standard[n - 1]
        if last == expected or (len(last) >= _MIN_PARTIAL_WORD and expected.startswith(last)):
            return True
    # A shortened title of two or more words, such as "ABUSE AND DEPENDENCE".
    return n >= _MIN_SHORTENED_WORDS and any(
        standard[i : i + n] == line for i in range(len(standard) - n + 1)
    )


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
        current = int(number.split(".")[0]) if number and number != BOXED_WARNING else None
        heading = _heading(line, current)
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
    if "." not in number:
        # A top-level title continues while it is only the start of its standard title.
        title_words, standard = _words(title), _words(_TOP_LEVEL_TITLES[int(number)])
        return len(title_words) < len(standard) and title_words == standard[: len(title_words)]
    return title.endswith(_CONTINUES)
