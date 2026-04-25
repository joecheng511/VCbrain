-- DealBrain schema
-- Run with: psql $DATABASE_URL -f schema.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$ BEGIN
    CREATE TYPE entity_type AS ENUM ('Company', 'Person', 'Deal', 'Document');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE source_type AS ENUM ('email', 'crm', 'pdf', 'hr_record');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE conflict_status AS ENUM ('open', 'auto_resolved', 'human_resolved');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS entities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type            entity_type NOT NULL,
    name            TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_canonical
    ON entities (canonical_name, type);

CREATE TABLE IF NOT EXISTS sources (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type         source_type NOT NULL,
    external_id  TEXT NOT NULL,
    raw_content  JSONB,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sources_external ON sources (external_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_type_extid
    ON sources (type, external_id);

CREATE TABLE IF NOT EXISTS facts (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id    UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    attribute    TEXT NOT NULL,
    value        TEXT NOT NULL,
    source_id    UUID REFERENCES sources(id) ON DELETE SET NULL,
    confidence   REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    verified_by  TEXT,
    verified_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts (entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_attr   ON facts (entity_id, attribute);

CREATE TABLE IF NOT EXISTS conflicts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fact_a_id   UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    fact_b_id   UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    status      conflict_status NOT NULL DEFAULT 'open',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (fact_a_id <> fact_b_id)
);
CREATE INDEX IF NOT EXISTS idx_conflicts_status ON conflicts (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflicts_pair
    ON conflicts (LEAST(fact_a_id, fact_b_id), GREATEST(fact_a_id, fact_b_id));
