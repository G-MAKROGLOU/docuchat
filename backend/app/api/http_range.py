"""HTTP Range header parsing for one byte range (RFC 9110, section 14)."""

import re

_SINGLE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeNotSatisfiableError(ValueError):
    pass


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """(start, end), both inclusive, or None (no, bad or multi-range header): whole object.
    Raises RangeNotSatisfiableError when the range starts past the end of the object."""
    if not header:
        return None
    match = _SINGLE.fullmatch(header.strip())
    if not match or (not match[1] and not match[2]):
        return None
    if not match[1]:  # suffix form: the last N bytes
        suffix = int(match[2])
        if suffix == 0:
            raise RangeNotSatisfiableError(header)
        return max(size - suffix, 0), size - 1
    start = int(match[1])
    end = int(match[2]) if match[2] else size - 1
    if start >= size:
        raise RangeNotSatisfiableError(header)
    if end < start:
        return None
    return start, min(end, size - 1)
