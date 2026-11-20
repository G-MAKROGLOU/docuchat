"""Drug detection in a question: exact names first, then fuzzy, plain code.
Thresholds are starting values from measured look-alike scores; phase 7 calibrates them."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.ports import NameSimilarity

# A generic name is also matched without these salt or form words ("hydralazine").
_SALT_WORDS = {
    "hydrochloride", "hcl", "sodium", "potassium", "calcium", "magnesium", "succinate",
    "tartrate", "mesylate", "maleate", "fumarate", "citrate", "besylate", "bromide",
    "sulfate", "acetate", "phosphate", "monohydrate", "anhydrous", "extended", "release",
}  # fmt: skip
# Endings of drug names (stems). A word with one of them is a drug name, so when it is not
# in the corpus it is reported as not_in_corpus. ASSUMED heuristic, to review on the golden set.
_DRUG_ENDINGS = (
    "pril", "sartan", "statin", "olol", "azole", "prazole", "mab", "tinib", "ciclib",
    "vir", "tidine", "gliptin", "gliflozin", "xaban", "formin", "profen", "cillin",
    "mycin", "cycline", "floxacin", "dipine", "azepam", "zolam", "setron", "triptan",
    "lukast", "parin", "gatran", "afil", "oxetine", "pramine", "barbital", "semide",
)  # fmt: skip
_MIN_KEY_LENGTH = 4
_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")  # words of _MIN_KEY_LENGTH letters or more


@dataclass(frozen=True, slots=True)
class DrugEntry:
    name: str  # canonical name: the chunk drug_name filter value
    brand: str
    generic: str


@dataclass(frozen=True, slots=True)
class DrugDetection:
    drugs: tuple[str, ...] = ()
    fuzzy: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    not_in_corpus: tuple[str, ...] = ()


class DrugDetector:
    def __init__(
        self,
        entries: list[DrugEntry],
        similarity: NameSimilarity,
        *,
        fuzzy_threshold: float = 85.0,
        candidate_floor: float = 75.0,
        ambiguity_margin: float = 12.0,
    ) -> None:
        self._similarity = similarity
        self._threshold = fuzzy_threshold
        self._floor = candidate_floor
        self._margin = ambiguity_margin
        # Name key (lower case) -> canonical name. Longer keys first, for multi-word names.
        keys: dict[str, str] = {}
        for entry in entries:
            for key in _keys(entry):
                keys.setdefault(key, entry.name)
        self._keys = dict(sorted(keys.items(), key=lambda kv: -len(kv[0])))
        self._single_word_keys = {k: v for k, v in self._keys.items() if " " not in k}

    def detect(self, question: str) -> DrugDetection:
        text = question.lower()
        found: list[tuple[int, str]] = []
        taken: list[tuple[int, int]] = []
        for key, name in self._keys.items():
            for match in re.finditer(rf"\b{re.escape(key)}\b", text):
                if any(a < match.end() and match.start() < b for a, b in taken):
                    continue
                taken.append(match.span())
                found.append((match.start(), name))

        fuzzy: list[tuple[int, str]] = []
        ambiguous: list[list[str]] = []
        outside: list[str] = []
        for match in _WORD.finditer(text):
            if any(a < match.end() and match.start() < b for a, b in taken):
                continue
            word = match[0]
            ranked = self._rank(word)
            if (
                ranked
                and ranked[0][1] >= self._threshold
                and (len(ranked) == 1 or ranked[1][1] < ranked[0][1] - self._margin)
            ):
                fuzzy.append((match.start(), ranked[0][0]))
            elif len(ranked) > 1 and ranked[1][1] >= ranked[0][1] - self._margin:
                ambiguous.append([name for name, _ in ranked])
            elif word.endswith(_DRUG_ENDINGS) and not any(word == e for e in _DRUG_ENDINGS):
                outside.append(word)

        drugs = _unique(name for _, name in sorted(found + fuzzy))
        return DrugDetection(
            drugs=drugs,
            fuzzy=_unique(name for _, name in fuzzy if name in drugs),
            # A word close to a drug the question already names refers to that drug.
            ambiguous=_unique(
                n for group in ambiguous if not set(group) & set(drugs) for n in group
            ),
            not_in_corpus=_unique(outside),
        )

    def _rank(self, word: str) -> list[tuple[str, float]]:
        """Canonical names whose best key scores at least the floor, best first."""
        best: dict[str, float] = {}
        for key, name in self._single_word_keys.items():
            score = self._similarity.ratio(word, key)
            if score >= self._floor and score > best.get(name, 0):
                best[name] = score
        return sorted(best.items(), key=lambda kv: -kv[1])


def _keys(entry: DrugEntry) -> set[str]:
    keys = {entry.brand.lower(), entry.generic.lower()}
    base = [w for w in entry.generic.lower().split() if w not in _SALT_WORDS]
    if base:
        keys.add(" ".join(base))
    return {k for k in keys if len(k) >= _MIN_KEY_LENGTH}


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))
