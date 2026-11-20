"""TextSplitter and TokenCounter adapters: LangChain sentence splitting, tiktoken counting."""

from functools import cache

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.domain.entities import TextSpan

# text-embedding-3-small uses this encoding.
ENCODING = "cl100k_base"
# Lines (paragraphs, list items, table rows) first, then sentence ends; smaller units only
# for a sentence longer than the chunk size.
SEPARATORS = ["\n", ". ", "; ", ", ", " ", ""]


@cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING)


class TiktokenCounter:
    def count(self, text: str) -> int:
        return len(_encoding().encode(text))


class SentenceTokenSplitter:
    def __init__(self, chunk_tokens: int = 500, overlap_tokens: int = 50) -> None:
        # keep_separator="end" keeps ". " on the sentence it ends, so every span starts a sentence.
        self._splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name=ENCODING,
            chunk_size=chunk_tokens,
            chunk_overlap=overlap_tokens,
            separators=SEPARATORS,
            keep_separator="end",
            strip_whitespace=True,
        )

    def split(self, text: str) -> list[TextSpan]:
        # LangChain's start_index does not match these settings, so search forward instead:
        # spans are in order, and each starts after the start of the one before it.
        spans: list[TextSpan] = []
        search_from = 0
        for piece in self._splitter.split_text(text):
            start = text.find(piece, search_from)
            if start < 0:
                raise ValueError("Splitter returned text that is not in the input")
            spans.append(TextSpan(start=start, text=piece))
            search_from = start + 1
        return spans
