"""LabelParser adapter for SPL XML, the HL7 structured product label that DailyMed publishes."""

import pyexpat
from xml.etree import ElementTree  # nosec B405  # safe with the expat check below

from app.domain.entities import LabelNode

_V = "{urn:hl7-org:v3}"
# expat 2.4.1+ limits entity expansion (billion laughs); ElementTree loads no external entities.
if pyexpat.version_info < (2, 4, 1):
    raise RuntimeError(f"expat {pyexpat.EXPAT_VERSION} is too old to parse SPL safely")

_LINES = {"paragraph", "caption", "list", "table"}
_CELLS = {"td", "th"}


class SplXmlParser:
    def sections(self, data: bytes) -> list[LabelNode]:
        root = ElementTree.fromstring(data)  # noqa: S314  # nosec B314  # expat checked above
        body = root.find(f"{_V}component/{_V}structuredBody")
        if body is None:
            raise ValueError("The SPL has no structured body")
        return [_node(s) for s in body.findall(f"{_V}component/{_V}section")]


def _node(section: ElementTree.Element) -> LabelNode:
    code = section.find(f"{_V}code")
    return LabelNode(
        code=code.get("code", "") if code is not None else "",
        title=_inline(section.find(f"{_V}title")),
        text=_text(section.find(f"{_V}text")),
        children=tuple(_node(s) for s in section.findall(f"{_V}component/{_V}section")),
    )


def _inline(element: ElementTree.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _text(element: ElementTree.Element | None) -> str:
    """Paragraphs, list items and table rows on their own lines; cells joined with " | "."""
    if element is None:
        return ""
    out: list[str] = []
    _walk(element, out)
    lines: list[str] = []
    marker = ""
    for line in (" ".join(raw.split()) for raw in "".join(out).split("\n")):
        if line == "-":  # an item whose text starts with a paragraph
            marker = "- "
        elif line.replace("|", "").strip():  # not a table row of empty cells
            lines.append(marker + line)
            marker = ""
    return "\n".join(lines)


def _flat(text: str | None) -> str:
    return " ".join((text or "").splitlines())


def _walk(element: ElementTree.Element, out: list[str]) -> None:
    tag = element.tag.removeprefix(_V)
    if tag == "tr":
        cells = [_inline(c) for c in element if c.tag.removeprefix(_V) in _CELLS]
        out.append("\n" + " | ".join(cells) + "\n")
        return
    if tag == "br":
        out.append("\n")
    elif tag == "item":
        out.append("\n- ")
    elif tag in _LINES:
        out.append("\n")
    # Line breaks in the source are layout only; the structure gives the real ones.
    out.append(_flat(element.text))
    for child in element:
        # The caption of a list item is its bullet; the "- " marker replaces it.
        if not (tag == "item" and child.tag == f"{_V}caption"):
            _walk(child, out)
        out.append(_flat(child.tail))
    if tag in _LINES or tag == "item":
        out.append("\n")
