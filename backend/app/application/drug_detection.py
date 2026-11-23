"""Drug detection in a question: exact names first, then fuzzy, plain code.
Thresholds calibrated on 2026-11-23 with evals/detector_calibration.py (see docs/agent-log.md)."""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.domain.ports import NameSimilarity

# A generic name is also matched without these salt or form words ("hydralazine").
_SALT_WORDS = {
    "hydrochloride", "hcl", "sodium", "potassium", "calcium", "magnesium", "succinate",
    "tartrate", "mesylate", "maleate", "fumarate", "citrate", "besylate", "bromide",
    "sulfate", "acetate", "phosphate", "monohydrate", "anhydrous", "extended", "release",
    "bitartrate",
}  # fmt: skip
# Route words of a generic name ("oral semaglutide"); the dosage form tells the product apart.
_ROUTE_WORDS = {"oral", "topical", "ophthalmic", "nasal", "transdermal", "injectable"}
# Endings of drug names (stems). A word with one of them is a drug name, so when it is not
# in the corpus it is reported as not_in_corpus. ASSUMED heuristic, to review on the golden set.
_DRUG_ENDINGS = (
    "pril", "sartan", "statin", "olol", "azole", "prazole", "mab", "tinib", "ciclib",
    "vir", "tidine", "gliptin", "gliflozin", "xaban", "formin", "profen", "cillin",
    "mycin", "cycline", "floxacin", "dipine", "azepam", "zolam", "setron", "triptan",
    "lukast", "parin", "gatran", "afil", "oxetine", "pramine", "barbital", "semide",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class DetectorThresholds:
    """Calibrated values (evals/detector_calibration.py)."""

    min_key_length: int
    # Shorter word tails ("statin", "pril") are name stems, not drug names.
    min_tail_length: int
    fuzzy_threshold: float
    candidate_floor: float
    ambiguity_margin: float
    # A clarify question offers at most this many medicines, best first.
    max_choices: int


@dataclass(frozen=True, slots=True)
class DrugEntry:
    """One label. The detector takes the entries in preference order: the first label of a
    product is the one that answers for it."""

    name: str  # display name: brand, else generic
    brand: str
    generic: str
    label: UUID = field(default_factory=uuid4)  # the document ID, the search filter
    form: str = ""  # SPL dosage form, for example "TABLET, FILM COATED"


@dataclass(frozen=True, slots=True)
class DrugDetection:
    drugs: tuple[str, ...] = ()
    fuzzy: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    not_in_corpus: tuple[str, ...] = ()
    labels: tuple[UUID, ...] = ()  # the preferred label of each drug, in the order of drugs


@dataclass(frozen=True, slots=True)
class _Product:
    name: str
    label: UUID
    form: str  # form group: "tablet", "injection"


def form_group(dosage_form: str) -> str:
    """The first part of an SPL dosage form: "TABLET, FILM COATED" is a tablet."""
    return dosage_form.split(",", maxsplit=1)[0].strip().lower()


def product_key(generic: str, dosage_form: str) -> str:
    """A product is its active ingredients plus its dosage form group. Generic labels of one
    product carry the text of the brand label, so one label answers for all of them."""
    parts = re.split(r",|/| and | with ", generic.lower())
    drop = _SALT_WORDS | _ROUTE_WORDS
    ingredients = {" ".join(w for w in part.split() if w not in drop) for part in parts}
    return f"{'+'.join(sorted(ingredients - {''}))}|{form_group(dosage_form)}"


def _catalog_name(entry: DrugEntry) -> str:
    if entry.brand and entry.generic and entry.brand.lower() != entry.generic.lower():
        return f"{entry.brand} ({entry.generic})"
    return entry.brand or entry.generic or entry.name


class DrugDetector:
    def __init__(
        self,
        entries: list[DrugEntry],
        similarity: NameSimilarity,
        thresholds: DetectorThresholds,
    ) -> None:
        self._similarity = similarity
        self._limits = thresholds
        self._threshold = thresholds.fuzzy_threshold
        self._floor = thresholds.candidate_floor
        self._margin = thresholds.ambiguity_margin
        # Words of min_key_length letters or more.
        self._word = re.compile(rf"[A-Za-z][A-Za-z\-]{{{thresholds.min_key_length - 1},}}")
        # Product key -> its preferred label (the first entry). Name key (lower case) ->
        # product keys; one name can cover more products: one brand as an injection and tablets.
        self._products: dict[str, _Product] = {}
        keys: dict[str, tuple[str, ...]] = {}
        for entry in entries:
            product = product_key(entry.generic or entry.name, entry.form)
            self._products.setdefault(
                product, _Product(entry.name, entry.label, form_group(entry.form))
            )
            for key in _keys(entry, thresholds.min_key_length):
                keys[key] = _unique((*keys.get(key, ()), product))
        self._keys = dict(sorted(keys.items(), key=lambda kv: -len(kv[0])))
        self._single_word_keys = {k: v for k, v in self._keys.items() if " " not in k}
        self._single_word_list = list(self._single_word_keys)
        # Every ending of a longer single-word name ("omeprazole" of "esomeprazole"), for _is_tail.
        self._tails = {
            key[i:]
            for key in self._single_word_list
            for i in range(1, len(key) - thresholds.min_tail_length + 1)
        }
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
        # Names that cover several products and a question that names no form: ask which.
        forms: list[tuple[int, list[str]]] = []
        if self._key_pattern is not None:
            for match in self._key_pattern.finditer(text):
                taken.append(match.span())
                found.extend(self._pick(match.start(), self._keys[match[0]], text, forms))

        fuzzy: list[tuple[int, str]] = []
        ambiguous: list[tuple[int, list[str]]] = forms
        outside: list[str] = []
        for match in self._word.finditer(text):
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
                fuzzy.extend(self._pick(match.start(), ranked[0][0], text, forms))
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

        products = _unique(key for _, key in sorted(found + fuzzy))
        fuzzy_products = {key for _, key in fuzzy}
        return DrugDetection(
            drugs=tuple(self._products[key].name for key in products),
            fuzzy=_unique(self._products[key].name for key in products if key in fuzzy_products),
            ambiguous=self._choices(_unique(unresolved)),
            not_in_corpus=_unique(outside),
            labels=tuple(self._products[key].label for key in products),
        )

    def _pick(
        self, start: int, group: Sequence[str], text: str, forms: list[tuple[int, list[str]]]
    ) -> list[tuple[int, str]]:
        """The products of one name: all when it is one, else the ones whose dosage form the
        question names. With no form named, the group waits in forms for a clarify question."""
        if len(group) == 1:
            return [(start, group[0])]
        named = [key for key in group if _names_form(text, self._products[key].form)]
        if not named:
            forms.append((start, list(group)))
        return [(start, key) for key in named]

    def _choices(self, keys: Sequence[str]) -> tuple[str, ...]:
        """Clarify candidates; a name shared by two products gets its form: "Ozempic (tablet)"."""
        keys = keys[: self._limits.max_choices]
        names = [self._products[key].name.casefold() for key in keys]
        return tuple(
            f"{self._products[key].name} ({self._products[key].form})"
            if names.count(name) > 1 and self._products[key].form
            else self._products[key].name
            for key, name in zip(keys, names, strict=True)
        )

    def _is_tail(self, word: str) -> bool:
        """The word ends a longer library name ("omeprazole" in "esomeprazole"): another drug,
        though its fuzzy score is high (calibration 2026-11-23)."""
        return len(word) >= self._limits.min_tail_length and word in self._tails

    def _rank(self, word: str) -> list[tuple[tuple[str, ...], float]]:
        """Product groups (the products of one name key) whose best key scores at least the
        floor, best first."""
        best: dict[tuple[str, ...], float] = {}
        for key, score in self._similarity.best(word, self._single_word_list, self._floor):
            products = self._single_word_keys[key]
            if score > best.get(products, 0):
                best[products] = score
        return sorted(best.items(), key=lambda kv: -kv[1])


def _keys(entry: DrugEntry, min_length: int) -> set[str]:
    keys = {entry.brand.lower(), entry.generic.lower()}
    base = [w for w in entry.generic.lower().split() if w not in _SALT_WORDS]
    if base:
        keys.add(" ".join(base))
    return {k for k in keys if len(k) >= min_length}


def _names_form(text: str, form: str) -> bool:
    """The question names the dosage form: "tablet", "tablets", "injection"."""
    return bool(form) and re.search(rf"\b{re.escape(form)}s?\b", text) is not None


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


class DetectorCache[T]:
    """Builds the detector once per library version. The version check is one small query;
    the build reads every document, so it runs only after the library changed. A new version
    rebuilds it at most once per min_interval seconds."""

    def __init__(
        self,
        version: Callable[[], Awaitable[object]],
        build: Callable[[], Awaitable[T]],
        *,
        min_interval: float,
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
