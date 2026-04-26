# VC Brain

A **VC fund intelligence** demo built on a PostgreSQL **fact graph**: companies, attributed facts with provenance, and explicit **data conflicts**. It ships with a **FastAPI** backend and a single-page **web UI** (`vcbrain.html`) served at the root URL.

Use it to explore portfolio entities, resolve conflict queues, ask natural-language questions via a **Claude-powered chat router**, generate **investment briefs**, and run a **prompt evolution harness** that improves the analyst prompt against fixed test cases.

## Features

| Area | What you get |
|------|----------------|
| **Brain overview** | Portfolio stats, interactive force-directed knowledge graph (D3), conflict highlights |
| **Conflict queue** | Open conflicts with links to source context; resolve via API |
| **Company brief** | Search by name; facts and conflicts from the graph |
| **Ask VC Brain** | `POST /chat` — intent routing (company, sector, stats, conflicts, comparison, general, …) + Claude answers with fund context |
| **Harness evolution** | Background loop: score briefs on test cases, ask Claude to rewrite the system prompt; **live progress** in the UI (per-case activity + log) |
| **Investment brief JSON** | `GET /brief/{name}` — structured verdict via the same harness pipeline |

## Stack

- **Python** 3.12+ (3.13 supported)
- **FastAPI** + **Uvicorn**
- **PostgreSQL** 14+ (`uuid-ossp`; schema in `schema.sql`)
- **psycopg2** (thread-safe pool)
- **Anthropic** [Messages API](https://docs.anthropic.com/) — default model **`claude-sonnet-4-6`** (override with `ANTHROPIC_MODEL`)
- Optional: **Pioneer / GLiNER2**-style context compaction for the harness (`PIONEER_API_KEY`, `COMPACT_CONTEXT`, … in `app/config.py`)

## Quick start

### 1. Create the database

```bash
createdb dealbrain
psql dealbrain -f schema.sql
```

### 2. Install dependencies

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

- **`DATABASE_URL`** — PostgreSQL connection string
- **`ANTHROPIC_API_KEY`** — required for `/chat`, `/brief/{name}`, and harness evolution
- **`ANTHROPIC_MODEL`** — optional; defaults to `claude-sonnet-4-6`

See `.env.example` for CORS, DB pool size, and **`HARNESS_AUTO_RUN`** / **`HARNESS_MAX_ITERATIONS`**.

### 4. Load data

If you use the bundled seed:

```bash
python -m app.seed
```

For a full demo (hundreds of companies + conflicts), load your own JSON into PostgreSQL using your existing ingestion path (e.g. `vcbrain_data/` → DB).

### 5. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** for the UI, or **http://localhost:8000/docs** for OpenAPI.

## API overview

| Method | Path | Purpose |
|--------|------|--------|
| GET | `/` | Web UI (`vcbrain.html`) |
| GET | `/health` | Liveness |
| GET | `/entity/{name}` | Entity + facts + conflicts |
| GET | `/conflicts` | Conflict list (optional filters) |
| PATCH | `/conflicts/{id}/resolve` | Mark conflict human-resolved |
| GET | `/entities/count` | Entity and fact counts |
| GET | `/entities/by-sector` | Sector rollup (counts, ARR, open conflicts) |
| GET | `/brief/{name}` | Claude investment brief (JSON); TTL-cached |
| POST | `/chat` | Chat body: `{ "message": "..." }` → `{ intent, text }` (HTML in `text`) |
| POST | `/harness/run` | Start evolution (`max_iterations` query param) |
| GET | `/harness/status` | State, iterations, **live progress** fields while running |
| POST | `/harness/stop` | Stop after current iteration |
| POST | `/harness/reset` | Clear harness state (not while running) |

Lookup for entities is case-insensitive (`canonical_name`).

## Response shape (`GET /entity/{name}`)

```json
{
  "entity": { "id": "uuid", "type": "Company", "name": "Example GmbH" },
  "facts": [
    {
      "attribute": "arr_eur",
      "value": "1200000",
      "confidence": 0.95,
      "source": { "type": "crm", "external_id": "..." }
    }
  ],
  "conflicts": [
    {
      "attribute": "arr_eur",
      "value_a": "1200000",
      "value_b": "980000",
      "status": "open"
    }
  ]
}
```

## Schema (summary)

Defined in `schema.sql`:

- **`entities`** — companies and other nodes; `canonical_name` for deduplication
- **`sources`** — provenance (`email`, `crm`, `pdf`, …)
- **`facts`** — `entity_id`, `attribute`, `value`, `source_id`, `confidence`
- **`conflicts`** — pairs of facts, `status`: `open` | `auto_resolved` | `human_resolved`

## Repository layout

```
schema.sql
vcbrain.html                 # SPA UI (served by FastAPI)
vcbrain_data/                # Sample / import JSON (optional)
vcbrain_tasks/
  test_cases.json            # Harness eval cases
  evolution_state.json       # Persisted best prompt + run history (generated)
vcbrain_harness/
  harness.py                 # Brief generation (HTTP to Layer 2 + Claude)
  evolution.py               # Prompt evolution loop + live progress fields
  claude_util.py             # Shared Anthropic client helpers
app/
  main.py                    # App entry, CORS, `/`, `/brief`, cache
  config.py                  # Settings from env
  db.py                      # Connection pool
  routes/
    entities.py              # Entities, conflicts, sector rollup
    harness.py               # Harness HTTP API
    chat.py                  # Claude chat router + fund context
```

## Development notes

- **Secrets**: never commit `.env` or real API keys. `.env.example` uses placeholders only.
- **Harness**: evolution runs in a background thread; the UI polls `/harness/status` about once per second while `status` is `running`.
- **Partner integrations**: you can still treat `GET /entity/{name}` and related JSON as a stable contract for downstream services.

## License

Use and modify per your organization’s policy.
