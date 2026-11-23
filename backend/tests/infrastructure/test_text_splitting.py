"""The real splitter: size limit, overlap and sentence boundaries."""

import itertools
import re

from app.infrastructure.text_splitting import SentenceTokenSplitter, TiktokenCounter

SENTENCE = "The recommended starting dose is {n} mg taken once daily with or without food."
TEXT = " ".join(SENTENCE.format(n=i) for i in range(1, 121))


def test_spans_respect_the_token_limit_and_overlap() -> None:
    counter = TiktokenCounter()
    spans = SentenceTokenSplitter(chunk_tokens=100, overlap_tokens=20).split(TEXT)

    assert len(spans) > 5
    assert all(counter.count(s.text) <= 100 for s in spans)
    # Consecutive spans share whole sentences, no more than the overlap budget.
    for previous, current in itertools.pairwise(spans):
        shared = previous.text[current.start - previous.start :]
        assert counter.count(shared) <= 20


def test_every_span_starts_and_ends_at_a_sentence_boundary() -> None:
    spans = SentenceTokenSplitter(chunk_tokens=100, overlap_tokens=20).split(TEXT)

    for span in spans:
        assert span.text.startswith("The recommended")
        assert span.text.endswith("food.")
        assert TEXT[span.start : span.start + len(span.text)] == span.text


def test_spans_cover_the_whole_text() -> None:
    spans = SentenceTokenSplitter(chunk_tokens=100, overlap_tokens=20).split(TEXT)
    numbers = {int(n) for s in spans for n in re.findall(r"dose is (\d+) mg", s.text)}

    assert numbers == set(range(1, 121))


def test_short_text_is_one_span() -> None:
    spans = SentenceTokenSplitter(chunk_tokens=500, overlap_tokens=50).split(
        "Take one tablet daily."
    )

    assert [(s.start, s.text) for s in spans] == [(0, "Take one tablet daily.")]
