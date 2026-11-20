"""Turn the section tree of a structured label (SPL) into the numbered prescribing sections.
Numbers come from the titles; the SPL codes subsections only as "unclassified"."""

import logging
import re
from collections.abc import Iterator, Sequence

from app.domain.entities import LabelNode, LabelSection

BOXED_WARNING = "BW"
BOXED_WARNING_CODE = "34066-1"
_TOP_LEVEL_SECTIONS = 17  # 21 CFR 201.57(c)
# Highlights, recent major changes, patient guides and the package label.
_NOT_BODY = {"48780-1", "43683-2", "42230-3", "42231-1", "59845-8", "51945-4"}
# "5.1 0 Title" and "14 .1 Title": the SPL titles keep spaces from the source layout.
# A spaced digit joins the number only before a capital, so "2.1 5 mg Tablets" stays 2.1.
_NUMBERED = re.compile(r"^(\d{1,2}(?:\s*\.\s*\d(?:\d|\s\d(?=\s+[A-Z(\[]))?)*)\s*\.?\s+(\S.*)$")

logger = logging.getLogger(__name__)


class LabelFormatError(ValueError):
    pass


def split_sections(nodes: Sequence[LabelNode]) -> list[LabelSection]:
    sections: list[LabelSection] = []
    for node in nodes:
        if node.code == BOXED_WARNING_CODE:
            sections.extend(_sections(node, BOXED_WARNING, _clean(node.title)))
            continue
        numbered = _numbered(node.title)
        if numbered and 1 <= int(numbered[0].split(".")[0]) <= _TOP_LEVEL_SECTIONS:
            sections.extend(_sections(node, *numbered))
        elif node.code not in _NOT_BODY:
            logger.info("section skipped", extra={"code": node.code, "title": node.title})
    if not sections:
        raise LabelFormatError("The label has no numbered prescribing information sections")
    return sections


def _numbered(title: str) -> tuple[str, str] | None:
    match = _NUMBERED.match(_clean(title))
    return (re.sub(r"\s", "", match[1]), match[2]) if match else None


def _clean(text: str) -> str:
    return " ".join(text.split())


def _sections(node: LabelNode, number: str, title: str) -> Iterator[LabelSection]:
    """The section, then its numbered descendants; unnumbered ones join the section text."""
    parts = [node.text] if node.text else []
    later: list[LabelNode] = []
    _collect(node.children, parts, later)
    yield LabelSection(number=number, title=title, text="\n".join(parts))
    for child in later:
        numbered = _numbered(child.title)
        if numbered:
            yield from _sections(child, *numbered)


def _collect(children: Sequence[LabelNode], parts: list[str], later: list[LabelNode]) -> None:
    for child in children:
        if child.code in _NOT_BODY:
            continue
        if _numbered(child.title):
            later.append(child)
            continue
        parts.extend(p for p in (_clean(child.title), child.text) if p)
        _collect(child.children, parts, later)
