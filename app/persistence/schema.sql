-- PIA-3 assistant schema.  Idempotent: safe to run on every start.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS notes (
    id            text PRIMARY KEY,
    ts            timestamptz NOT NULL,
    operator      text NOT NULL DEFAULT '',
    walk_id       text NOT NULL DEFAULT '',
    audio_url     text,
    photos        jsonb NOT NULL DEFAULT '[]'::jsonb,
    live          boolean NOT NULL DEFAULT false,
    status        text NOT NULL DEFAULT 'received',
    transcript    text,
    received_at   timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS parts (
    note_id       text PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    status        text NOT NULL DEFAULT 'draft',
    rows          jsonb NOT NULL DEFAULT '[]'::jsonb,
    safety        text,
    attempts      integer NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS attempts (
    id            text PRIMARY KEY,
    note_id       text NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    message_id    text,
    kind          text NOT NULL,
    rows          jsonb NOT NULL DEFAULT '[]'::jsonb,
    reply         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tablet_messages (
    id            text PRIMARY KEY,
    note_id       text,
    ts            timestamptz NOT NULL,
    kind          text NOT NULL,
    payload       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS replies (
    id            text PRIMARY KEY,
    message_id    text NOT NULL,
    note_id       text,
    text          text NOT NULL DEFAULT '',
    ts            timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id            text PRIMARY KEY,
    ts            timestamptz NOT NULL,
    type          text NOT NULL,
    equipment     text,
    origin        text NOT NULL,
    part_id       text,
    note_ids      jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary       text NOT NULL DEFAULT '',
    context       jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id            text PRIMARY KEY,
    equipment     text NOT NULL,
    tasks         jsonb NOT NULL DEFAULT '[]'::jsonb,
    state         text NOT NULL,
    payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS orders_open_idx ON orders (state, equipment);

CREATE TABLE IF NOT EXISTS decisions (
    id            bigserial PRIMARY KEY,
    order_id      text NOT NULL,
    decision      text NOT NULL,
    reasons       jsonb NOT NULL DEFAULT '[]'::jsonb,
    plant_state   jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sensor_state (
    tag           text NOT NULL,
    variable      text NOT NULL,
    active        boolean NOT NULL DEFAULT false,
    since         timestamptz,
    event_id      text,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tag, variable)
);

CREATE TABLE IF NOT EXISTS sync_queue (
    id            bigserial PRIMARY KEY,
    topic         text NOT NULL,
    payload       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    attempts      integer NOT NULL DEFAULT 0,
    acked         boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS sync_pending_idx ON sync_queue (acked, id);

CREATE TABLE IF NOT EXISTS usage_log (
    id            bigserial PRIMARY KEY,
    model         text NOT NULL,
    task          text NOT NULL,
    input_tokens  integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    latency_ms    integer NOT NULL DEFAULT 0,
    cost_usd      numeric(10, 6) NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id            text PRIMARY KEY,
    doc           text NOT NULL,
    number        text NOT NULL DEFAULT '',
    title         text NOT NULL DEFAULT '',
    section_key   text NOT NULL DEFAULT '',
    page          integer,
    current       boolean NOT NULL DEFAULT true,
    manufacturer  text NOT NULL DEFAULT '',
    equipment     jsonb NOT NULL DEFAULT '[]'::jsonb,
    citation      text NOT NULL,
    text          text NOT NULL,
    content_hash  text NOT NULL,
    embedding     vector(384),
    tsv           tsvector
);

CREATE INDEX IF NOT EXISTS rag_tsv_idx ON rag_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS rag_embedding_idx ON rag_chunks
    USING hnsw (embedding vector_cosine_ops);
