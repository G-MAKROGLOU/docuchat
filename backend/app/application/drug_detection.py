"""Drug detection in a question: exact names first, then fuzzy, plain code.
Thresholds calibrated on 2026-11-23 with evals/detector_calibration.py (see docs/agent-log.md)."""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Iterable
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
# Shorter word tails ("statin", "pril") are name stems, not drug names.
_MIN_TAIL_LENGTH = 7
# Calibrated values (evals/detector_calibration.py).
FUZZY_THRESHOLD = 80.0
CANDIDATE_FLOOR = 70.0
AMBIGUITY_MARGIN = 12.0
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


def _catalog_name(entry: DrugEntry) -> str:
    if entry.brand and entry.generic and entry.brand.lower() != entry.generic.lower():
        return f"{entry.brand} ({entry.generic})"
    return entry.brand or entry.generic or entry.name


class DrugDetector:
    def __init__(
        self,
        entries: list[DrugEntry],
        similarity: NameSimilarity,
        *,
        fuzzy_threshold: float = FUZZY_THRESHOLD,
        candidate_floor: float = CANDIDATE_FLOOR,
        ambiguity_margin: float = AMBIGUITY_MARGIN,
    ) -> None:
        self._similarity = similarity
        self._threshold = fuzzy_threshold
        self._floor = candidate_floor
        self._margin = ambiguity_margin
        # Name key (lower case) -> canonical names. Longer keys first, for multi-word names.
        # One key can name more labels: one brand as an injection and as tablets.
        keys: dict[str, tuple[str, ...]] = {}
        for entry in entries:
            for key in _keys(entry):
                keys[key] = _unique((*keys.get(key, ()), entry.name))
        self._keys = dict(sorted(keys.items(), key=lambda kv: -len(kv[0])))
        self._single_word_keys = {k: v for k, v in self._keys.items() if " " not in k}
        # One pattern for all keys, compiled once: per-key patterns overflowed the regex cache
        # with 2000 labels and cost 0.46 s per question. Longer keys first, as above.
        self._key_pattern = (
            re.compile(r"\b(?:" + "|".join(map(re.escape, self._keys)) + r")\b")
            if self._keys
            else None
        )
        self._catalog = sorted({_catalog_name(e) for e in entries}, key=str.lower)

    def catalog(self) -> list[str]:
        """One name per label, "Brand (generic)", sorted."""
        return list(self._catalog)

    def detect(self, question: str) -> DrugDetection:
        text = question.lower()
        found: list[tuple[int, str]] = []
        taken: list[tuple[int, int]] = []
        if self._key_pattern is not None:
            for match in self._key_pattern.finditer(text):
                taken.append(match.span())
                found.extend((match.start(), name) for name in self._keys[match[0]])

        fuzzy: list[tuple[int, str]] = []
        ambiguous: list[tuple[int, list[str]]] = []
        outside: list[str] = []
        for match in _WORD.finditer(text):
            if any(a < match.end() and match.start() < b for a, b in taken):
                continue
            word = match[0]
            if self._is_tail(word):
                outside.append(word)
                continue
            ranked = self._rank(word)
            if (
                ranked
                and ranked[0][1] >= self._threshold
                and (len(ranked) == 1 or ranked[1][1] < ranked[0][1] - self._margin)
            ):
                fuzzy.extend((match.start(), name) for name in ranked[0][0])
            elif len(ranked) > 1 and ranked[1][1] >= ranked[0][1] - self._margin:
                ambiguous.append((match.start(), list(_unique(n for g, _ in ranked for n in g))))
            elif word.endswith(_DRUG_ENDINGS) and not any(word == e for e in _DRUG_ENDINGS):
                outside.append(word)

        named = {name for _, name in found + fuzzy}
        unresolved: list[str] = []
        for start, group in ambiguous:
            rest = [name for name in group if name not in named]
            # Close to a drug the question names and to one other: the word means the other.
            if len(rest) == 1 and len(group) > 1:
                fuzzy.append((start, rest[0]))
            else:
                unresolved.extend(rest)

        drugs = _unique(name for _, name in sorted(found + fuzzy))
        return DrugDetection(
            drugs=drugs,
            fuzzy=_unique(name for _, name in sorted(fuzzy) if name in drugs),
            ambiguous=_unique(unresolved),
            not_in_corpus=_unique(outside),
        )

    def _is_tail(self, word: str) -> bool:
        """The word ends a longer library name ("omeprazole" in "esomeprazole"): another drug,
        though its fuzzy score is high (calibration 2026-11-23)."""
        return len(word) >= _MIN_TAIL_LENGTH and any(
            key != word and key.endswith(word) for key in self._single_word_keys
        )

    def _rank(self, word: str) -> list[tuple[tuple[str, ...], float]]:
        """Name groups (the labels of one key) whose best key scores at least the floor,
        best first."""
        best: dict[tuple[str, ...], float] = {}
        for key, names in self._single_word_keys.items():
            score = self._similarity.ratio(word, key)
            if score >= self._floor and score > best.get(names, 0):
                best[names] = score
        return sorted(best.items(), key=lambda kv: -kv[1])


def _keys(entry: DrugEntry) -> set[str]:
    keys = {entry.brand.lower(), entry.generic.lower()}
    base = [w for w in entry.generic.lower().split() if w not in _SALT_WORDS]
    if base:
        keys.add(" ".join(base))
    return {k for k in keys if len(k) >= _MIN_KEY_LENGTH}


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


# A new library version rebuilds the detector at most this often.
REBUILD_SECONDS = 30.0


class DetectorCache[T]:
    """Builds the detector once per library version. The version check is one small query;
    the build reads every document, so it runs only after the library changed."""

    def __init__(
        self,
        version: Callable[[], Awaitable[object]],
        build: Callable[[], Awaitable[T]],
        *,
        min_interval: float = REBUILD_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._version = version
        self._build = build
        self._min_interval = min_interval
        self._clock = clock
        self._lock = asyncio.Lock()
        self._built: tuple[object, T] | None = None
        self._built_at = 0.0

    def _current(self, built: tuple[object, T], version: object) -> bool:
        # During an ingestion pass the version changes with each document; a detector that
        # is a few seconds old is good enough, so it is rebuilt at most once per interval.
        return built[0] == version or self._clock() - self._built_at < self._min_interval

    async def __call__(self) -> T:
        version = await self._version()
        if self._built is not None and self._current(self._built, version):
            return self._built[1]
        async with self._lock:
            # Another call may have built it while this one waited.
            if self._built is None or not self._current(self._built, version):
                self._built = (version, await self._build())
                self._built_at = self._clock()
            return self._built[1]
