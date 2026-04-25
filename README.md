# DealBrain — Context Base (Layer 2)

Structured fact graph with provenance. The intelligence layer below RAG: not chunks, but verifiable facts an AI agent can operate on.

This repo is the Python backend that exposes a single REST endpoint to the Node/TS API:

```
GET /entity/{name}
  -> { entity, facts[], conflicts[] }
```

## Stack

- Python 3.12, FastAPI, Uvicorn
- PostgreSQL 14+ (with `uuid-ossp`)
- `psycopg2` — raw SQL, no ORM
- Anthropic Claude (`claude-sonnet-4-6`) for entity/fact extraction (Hour 2-5)

## Quick start

### 1. Create the database

```bash
createdb dealbrain
psql dealbrain -f schema.sql
```

### 2. Install Python deps

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure env

```bash
cp .env.example .env
# edit DATABASE_URL and ANTHROPIC_API_KEY
```

### 4. Seed mock data (50 facts)

```bash
python -m app.seed
```

### 5. Run the API

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Smoke test

```bash
curl http://localhost:8000/                          # health
curl http://localhost:8000/entity/Acme%20Corp        # full entity
curl http://localhost:8000/entity/Initech            # has an OPEN conflict
curl http://localhost:8000/entity/Globex%20Inc       # has an AUTO_RESOLVED conflict
```

Or open `http://localhost:8000/docs` for the auto-generated Swagger UI.

## Response shape (locked contract)

```json
{
  "entity": { "id": "uuid", "type": "Company", "name": "Acme Corp" },
  "facts": [
    {
      "attribute": "ceo",
      "value": "Alice Anderson",
      "confidence": 1.0,
      "source": { "type": "email", "external_id": "EMAIL-001" }
    }
  ],
  "conflicts": [
    {
      "attribute": "annual_revenue",
      "value_a": "$45M",
      "value_b": "$52M",
      "status": "open"
    }
  ]
}
```

Lookup is case-insensitive (matches against `entities.canonical_name`).

## Schema

Four tables — see `schema.sql`:

- `entities (id, type, name, canonical_name)` — `type` is `Company | Person | Deal | Document`
- `sources (id, type, external_id, raw_content, ingested_at)` — `type` is `email | crm | pdf | hr_record`
- `facts (id, entity_id, attribute, value, source_id, confidence, verified_by, verified_at)`
- `conflicts (id, fact_a_id, fact_b_id, status)` — `status` is `open | auto_resolved | human_resolved`

UUID primary keys throughout. `(canonical_name, type)` is uniquely indexed so we can dedup entities on insert. `raw_content` is JSONB so the original source record is preserved verbatim.

## Layout

```
schema.sql                  # DDL — run once
app/
  main.py                   # FastAPI app + lifespan
  config.py                 # env settings
  db.py                     # psycopg2 connection pool
  models.py                 # Pydantic response shapes
  routes/entities.py        # GET /entity/{name}
  seed.py                   # python -m app.seed
```

## Build status

| Hour     | Component                                         | Status      |
|----------|---------------------------------------------------|-------------|
| 0-2      | Schema + DB + 50 mock records                     | done        |
| 0-2      | FastAPI skeleton + `GET /entity/{name}`           | done        |
| 2-5      | Ingestion pipeline (EnterpriseBench + Claude)     | next        |
| 5-8      | Conflict detection                                | pending     |
| 8        | Integration checkpoint with partner               | pending     |
| 14-18    | `GET /conflicts` review queue                     | pending     |
| 18-22    | HubSpot live demo layer                           | stretch     |

## Constraints (do not violate)

- No UI, no auth — partner owns those.
- Every fact must link to a source. Broken provenance = lost demo.
- Response shape is part of the partner contract. Do not change keys.
