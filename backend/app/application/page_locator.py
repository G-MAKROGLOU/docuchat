"""Find the PDF pages of chunk texts. The PDF is a rendering of the same structured label,
so the letters and digits of a chunk appear in the page texts in about the same order."""

import bisect
import re
from collections.abc import Sequence

# Letters and digits of the start and the end of a chunk that must match.
WINDOW = 40
# Lines and table cells shorter than this match in too many places.
MIN_PIECE = 12
# Letters allowed between the start and the end of a chunk past its own (headers, footers).
SLACK = 300
# Page breaks one chunk can cross.
MAX_SPAN = 2
_CONTENTS = "fullprescribinginformationcontents"
_BODY = "fullprescribinginformation"


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class PageLocator:
    def __init__(self, pages: Sequence[str]) -> None:
        self._pages = [_normalized(p) for p in pages]
        self._starts: list[int] = []
        position = 0
        for text in self._pages:
            self._starts.append(position)
            position += len(text)
        self._text = "".join(self._pages)
        self._cursor = self._body_start()
        self._body_page = self._page(self._cursor)
        self.misses = 0

    def _body_start(self) -> int:
        # The highlights repeat body text, so the search starts at the body heading.
        contents = self._text.find(_CONTENTS)
        body = self._text.find(_BODY, contents + len(_CONTENTS)) if contents >= 0 else -1
        return max(body, 0)

    def _page(self, position: int) -> int:
        return bisect.bisect_right(self._starts, position)

    def locate_all(self, contents: Sequence[str]) -> list[tuple[int, int]]:
        """First and last page of each chunk; chunks in reading order. A table chunk whose cells
        the PDF orders differently is found by its lines and cells between its neighbours."""
        found = [self._match(c) for c in contents]
        # The last page of the match before each chunk, and the first page of the match after it.
        before: list[int] = []
        last = self._body_page
        for match in found:
            before.append(last)
            last = match[1] if match else last
        after: list[int] = []
        first = len(self._pages)
        for match in reversed(found):
            after.append(first)
            first = match[0] if match else first
        after.reverse()

        result: list[tuple[int, int]] = []
        for content, match, previous, following in zip(contents, found, before, after, strict=True):
            if match is not None:
                result.append(match)
                continue
            low, high = min(previous, following), max(previous, following)
            pieces = self._by_pieces(content, low, high)
            if pieces is None:
                self.misses += 1
            result.append(pieces or (low, high))
        return result

    def _match(self, content: str) -> tuple[int, int] | None:
        key = _normalized(content)
        if not key:
            return None
        head = key[:WINDOW]
        start = self._text.find(head, self._cursor)
        if start < 0:
            # The PDF order inside a page can differ a little from the label order.
            page_start = self._starts[self._page(self._cursor) - 1]
            start = self._text.find(head, page_start, self._cursor + len(head))
        if start < 0:
            return None
        self._cursor = start
        first = self._page(start)
        tail = self._text.find(key[-WINDOW:], start, start + len(key) + SLACK)
        if tail >= 0:
            return first, self._page(tail + min(WINDOW, len(key)) - 1)
        # The end is in another order (a table): take the last page that holds its lines or cells.
        pieces = self._by_pieces(content, first, min(first + MAX_SPAN, len(self._pages)))
        return first, max(first, pieces[1]) if pieces else first

    def _by_pieces(self, content: str, low: int, high: int) -> tuple[int, int] | None:
        pieces = [_normalized(p) for line in content.split("\n") for p in line.split(" | ")]
        pieces = [p for p in pieces if len(p) >= MIN_PIECE]
        counts = {
            page: sum(p in self._pages[page - 1] for p in pieces) for page in range(low, high + 1)
        }
        best = max(counts.values(), default=0)
        # A single cell can also match a heading; keep the pages with more than half the best count.
        hits = [page for page, count in counts.items() if count and 2 * count > best]
        return (hits[0], hits[-1]) if hits else None
