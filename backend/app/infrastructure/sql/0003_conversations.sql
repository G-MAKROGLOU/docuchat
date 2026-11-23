CREATE TABLE conversations (
    id          uuid PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE conversation_turns (
    id               uuid PRIMARY KEY,
    conversation_id  uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             text NOT NULL CHECK (role IN ('user', 'assistant')),
    text             text NOT NULL,
    citations        text[] NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX conversation_turns_conversation_idx ON conversation_turns (conversation_id, created_at);
