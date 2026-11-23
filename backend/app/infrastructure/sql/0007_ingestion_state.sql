-- One row: the ingest worker reports here, and the API processes read it and ask for passes.
CREATE TABLE ingestion_state (
    id              smallint PRIMARY KEY CHECK (id = 1),
    phase           text NOT NULL DEFAULT 'idle'
                    CHECK (phase IN ('idle', 'checking', 'downloading', 'ingesting')),
    requested_at    timestamptz,
    force_requested boolean NOT NULL DEFAULT false,
    next_run_at     timestamptz,
    heartbeat_at    timestamptz
);

INSERT INTO ingestion_state (id) VALUES (1);
