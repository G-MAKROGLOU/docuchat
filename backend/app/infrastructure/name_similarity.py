"""NameSimilarity adapter with rapidfuzz."""

from rapidfuzz import fuzz


class RapidFuzzSimilarity:
    def ratio(self, a: str, b: str) -> float:
        return float(fuzz.ratio(a, b))
