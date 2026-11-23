CREATE TABLE label_queue (
    set_id         text PRIMARY KEY,
    title          text NOT NULL,
    status         text NOT NULL CHECK (status IN ('queued', 'added', 'failed')),
    failure_reason text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
