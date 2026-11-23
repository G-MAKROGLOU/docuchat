import base64
import json
import struct

import pytest
from fastapi.testclient import TestClient

from app.application import chat, chat_prompts
from loadtest import fake_model

EXCERPTS = (
    "[S1] Lipitor, section 2 Dosage, page 3:\ntext\n\n"
    "[S2] Lipitor, section 5 Warnings, page 9:\nmore"
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for name in ("FAKE_COMPLETE_SECONDS", "FAKE_FIRST_TOKEN_SECONDS", "FAKE_EMBED_SECONDS"):
        monkeypatch.setenv(name, "0")
    monkeypatch.setenv("FAKE_TOKENS_PER_SECOND", "0")
    return TestClient(fake_model.build_app())


def ask(client: TestClient, system: str, user: str, **extra: object) -> str:
    body = {
        "model": "m",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        **extra,
    }
    response = client.post("/v1/chat/completions", json=body)
    assert response.status_code == 200
    return str(response.json()["choices"][0]["message"]["content"])


def test_intake_always_searches(client: TestClient) -> None:
    text = ask(client, chat.intake_prompt(["Lipitor"]), "What is the dose of Lipitor?")
    assert chat.parse_intake(text) == ("search", "")
    assert chat.intake_query(text) == "What is the dose of Lipitor?"


def test_rewrite_returns_the_question(client: TestClient) -> None:
    assert ask(client, chat_prompts.REWRITE, "dose of Lipitor?") == "dose of Lipitor?"


def test_suggest_returns_parseable_questions(client: TestClient) -> None:
    text = ask(client, chat_prompts.SUGGEST, "Question: q\n\nAnswer:\na")
    assert len(chat.parse_suggestions(text)) == 2


def test_grade_marks_every_excerpt_relevant(client: TestClient) -> None:
    schema = {"type": "json_schema", "json_schema": {"name": "reply", "schema": {}}}
    text = ask(
        client,
        chat_prompts.GRADE,
        f"Question: q\n\nExcerpts:\n\n{EXCERPTS}",
        response_format=schema,
    )
    assert chat.parse_grade(text, ["S1", "S2"]) == (["S1", "S2"], "sufficient", "")


def test_generate_streams_an_answer_that_passes_validation(client: TestClient) -> None:
    body = {
        "model": "m",
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            {"role": "system", "content": chat_prompts.GENERATE},
            {"role": "user", "content": f"Question: q\n\nExcerpts:\n\n{EXCERPTS}"},
        ],
    }
    with client.stream("POST", "/v1/chat/completions", json=body) as response:
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line[6:]) for line in lines[:-1]]
    answer = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert chat.cited_ids(answer, ["S1", "S2"]) == ["S1", "S2"]
    assert chunks[-1]["usage"]["completion_tokens"] > 0


@pytest.mark.parametrize("encoding", ["float", "base64"])
def test_embeddings_have_the_requested_size(client: TestClient, encoding: str) -> None:
    response = client.post(
        "/v1/embeddings",
        json={"model": "e", "input": ["a", "b"], "dimensions": 8, "encoding_format": encoding},
    )
    data = response.json()["data"]
    assert [d["index"] for d in data] == [0, 1]
    vector = data[0]["embedding"]
    if encoding == "base64":
        raw = base64.b64decode(vector)
        vector = list(struct.unpack(f"<{len(raw) // 4}f", raw))
    assert len(vector) == 8
