"""Seed the database with mock data for the partner integration checkpoint.

Run with:
    python -m app.seed

Idempotent: re-running will not duplicate entities/sources (UNIQUE indexes
on canonical_name+type and type+external_id). Facts/conflicts are wiped
for the seeded entities before re-insert so counts stay stable.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg2.extras

from .db import get_conn

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

ENTITIES: list[dict[str, str]] = [
    # Companies
    {"type": "Company", "name": "Acme Corp",            "canonical_name": "acme corp"},
    {"type": "Company", "name": "Globex Inc",           "canonical_name": "globex inc"},
    {"type": "Company", "name": "Initech",              "canonical_name": "initech"},
    # People
    {"type": "Person",  "name": "Alice Anderson",       "canonical_name": "alice anderson"},
    {"type": "Person",  "name": "Bob Brown",            "canonical_name": "bob brown"},
    {"type": "Person",  "name": "Carol Chen",           "canonical_name": "carol chen"},
    {"type": "Person",  "name": "Dan Davis",            "canonical_name": "dan davis"},
    # Deals
    {"type": "Deal",    "name": "Acme Q4 Renewal",      "canonical_name": "acme q4 renewal"},
    {"type": "Deal",    "name": "Globex Expansion",     "canonical_name": "globex expansion"},
    # Documents
    {"type": "Document","name": "MSA-2024-Acme",        "canonical_name": "msa-2024-acme"},
]

SOURCES: list[dict[str, Any]] = [
    {"type": "email",     "external_id": "EMAIL-001", "raw_content": {"subject": "Re: Q4 renewal", "from": "alice@acme.com"}},
    {"type": "email",     "external_id": "EMAIL-002", "raw_content": {"subject": "Welcome to the team", "from": "hr@globex.com"}},
    {"type": "email",     "external_id": "EMAIL-003", "raw_content": {"subject": "Updated pricing", "from": "bob@initech.com"}},
    {"type": "crm",       "external_id": "CRM-DEAL-1001", "raw_content": {"object": "deal", "stage": "negotiation"}},
    {"type": "crm",       "external_id": "CRM-DEAL-1002", "raw_content": {"object": "deal", "stage": "closed_won"}},
    {"type": "crm",       "external_id": "CRM-CONTACT-77", "raw_content": {"object": "contact", "lifecycle": "customer"}},
    {"type": "pdf",       "external_id": "PDF-MSA-2024-001", "raw_content": {"pages": 14, "title": "Master Services Agreement"}},
    {"type": "pdf",       "external_id": "PDF-PITCH-2024", "raw_content": {"pages": 22, "title": "Globex pitch deck"}},
    {"type": "hr_record", "external_id": "HR-EMP-4521", "raw_content": {"system": "Workday", "module": "employee"}},
    {"type": "hr_record", "external_id": "HR-EMP-4522", "raw_content": {"system": "Workday", "module": "employee"}},
]

# (entity_name, attribute, value, source_external_id, confidence)
FACTS: list[tuple[str, str, str, str | None, float]] = [
    # Acme Corp (6)
    ("Acme Corp", "industry",         "Manufacturing",     "CRM-DEAL-1001", 1.0),
    ("Acme Corp", "headquarters",     "San Francisco, CA", "CRM-DEAL-1001", 1.0),
    ("Acme Corp", "employee_count",   "1200",              "PDF-MSA-2024-001", 0.7),
    ("Acme Corp", "founded_year",     "1998",              "PDF-MSA-2024-001", 1.0),
    ("Acme Corp", "ceo",              "Alice Anderson",    "EMAIL-001", 1.0),
    ("Acme Corp", "annual_revenue",   "$45M",              "PDF-MSA-2024-001", 0.7),
    # Globex Inc (6)
    ("Globex Inc", "industry",        "Software",          "CRM-DEAL-1002", 1.0),
    ("Globex Inc", "headquarters",    "Austin, TX",        "PDF-PITCH-2024", 1.0),
    ("Globex Inc", "employee_count",  "350",               "PDF-PITCH-2024", 1.0),
    ("Globex Inc", "founded_year",    "2012",              "PDF-PITCH-2024", 1.0),
    ("Globex Inc", "ceo",             "Carol Chen",        "EMAIL-002", 1.0),
    ("Globex Inc", "annual_revenue",  "$12M",              "PDF-PITCH-2024", 0.7),
    # Initech (5)
    ("Initech", "industry",           "IT Services",       "EMAIL-003", 1.0),
    ("Initech", "headquarters",       "Houston, TX",       "EMAIL-003", 0.7),
    ("Initech", "employee_count",     "80",                "EMAIL-003", 0.4),
    ("Initech", "founded_year",       "1999",              "EMAIL-003", 1.0),
    ("Initech", "ceo",                "Bob Brown",         "EMAIL-003", 1.0),
    # Alice Anderson (5)
    ("Alice Anderson", "title",       "CEO",               "EMAIL-001", 1.0),
    ("Alice Anderson", "company",     "Acme Corp",         "EMAIL-001", 1.0),
    ("Alice Anderson", "email",       "alice@acme.com",    "EMAIL-001", 1.0),
    ("Alice Anderson", "start_date",  "2015-03-01",        "HR-EMP-4521", 1.0),
    ("Alice Anderson", "department",  "Executive",         "HR-EMP-4521", 1.0),
    # Bob Brown (5)
    ("Bob Brown", "title",            "CEO",               "EMAIL-003", 1.0),
    ("Bob Brown", "company",          "Initech",           "EMAIL-003", 1.0),
    ("Bob Brown", "email",            "bob@initech.com",   "EMAIL-003", 1.0),
    ("Bob Brown", "start_date",       "2010-06-15",        "HR-EMP-4522", 1.0),
    ("Bob Brown", "salary",           "$220000",           "HR-EMP-4522", 1.0),
    # Carol Chen (4)
    ("Carol Chen", "title",           "CEO",               "EMAIL-002", 1.0),
    ("Carol Chen", "company",         "Globex Inc",        "EMAIL-002", 1.0),
    ("Carol Chen", "email",           "carol@globex.com",  "CRM-CONTACT-77", 1.0),
    ("Carol Chen", "department",      "Executive",         "CRM-CONTACT-77", 1.0),
    # Dan Davis (4)
    ("Dan Davis", "title",            "VP Sales",          "CRM-CONTACT-77", 1.0),
    ("Dan Davis", "company",          "Globex Inc",        "CRM-CONTACT-77", 1.0),
    ("Dan Davis", "manager",          "Carol Chen",        "CRM-CONTACT-77", 0.7),
    ("Dan Davis", "email",            "dan@globex.com",    "EMAIL-002", 1.0),
    # Acme Q4 Renewal (5)
    ("Acme Q4 Renewal", "deal_size",  "$250000",           "CRM-DEAL-1001", 1.0),
    ("Acme Q4 Renewal", "stage",      "negotiation",       "CRM-DEAL-1001", 1.0),
    ("Acme Q4 Renewal", "owner",      "Dan Davis",         "CRM-DEAL-1001", 1.0),
    ("Acme Q4 Renewal", "close_date", "2024-12-31",        "CRM-DEAL-1001", 0.7),
    ("Acme Q4 Renewal", "customer",   "Acme Corp",         "CRM-DEAL-1001", 1.0),
    # Globex Expansion (5)
    ("Globex Expansion", "deal_size", "$1200000",          "CRM-DEAL-1002", 1.0),
    ("Globex Expansion", "stage",     "closed_won",        "CRM-DEAL-1002", 1.0),
    ("Globex Expansion", "owner",     "Dan Davis",         "CRM-DEAL-1002", 1.0),
    ("Globex Expansion", "close_date","2024-09-30",        "CRM-DEAL-1002", 1.0),
    ("Globex Expansion", "customer",  "Globex Inc",        "CRM-DEAL-1002", 1.0),
    # MSA-2024-Acme (5)
    ("MSA-2024-Acme", "doc_type",     "Master Services Agreement", "PDF-MSA-2024-001", 1.0),
    ("MSA-2024-Acme", "signed_date",  "2024-02-14",                "PDF-MSA-2024-001", 1.0),
    ("MSA-2024-Acme", "party_a",      "Acme Corp",                 "PDF-MSA-2024-001", 1.0),
    ("MSA-2024-Acme", "party_b",      "Initech",                   "PDF-MSA-2024-001", 1.0),
    ("MSA-2024-Acme", "term_years",   "3",                         "PDF-MSA-2024-001", 1.0),
]

# Conflicts created via additional contradictory facts.
# (entity_name, attribute, value, source_external_id, confidence, partner_attribute_value_to_collide_with)
CONFLICT_FACTS: list[tuple[str, str, str, str, float, str]] = [
    # OPEN: Initech employee_count says 80 (low conf 0.4), pitch says 95
    ("Initech", "employee_count", "95", "PDF-PITCH-2024", 0.7, "80"),
    # OPEN: Acme annual_revenue says $45M (conf 0.7), CRM says $52M
    ("Acme Corp", "annual_revenue", "$52M", "CRM-DEAL-1001", 1.0, "$45M"),
    # AUTO_RESOLVED: Globex headquarters "Austin, TX" vs "austin, tx  "
    ("Globex Inc", "headquarters", "austin, tx  ", "EMAIL-002", 0.7, "Austin, TX"),
]


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------

_INSERT_ENTITY = """
    INSERT INTO entities (type, name, canonical_name)
    VALUES (%s, %s, %s)
    ON CONFLICT (canonical_name, type) DO UPDATE SET name = EXCLUDED.name
    RETURNING id
"""

_INSERT_SOURCE = """
    INSERT INTO sources (type, external_id, raw_content)
    VALUES (%s, %s, %s::jsonb)
    ON CONFLICT (type, external_id) DO UPDATE SET raw_content = EXCLUDED.raw_content
    RETURNING id
"""

_INSERT_FACT = """
    INSERT INTO facts (entity_id, attribute, value, source_id, confidence)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id
"""

_FIND_FACT = """
    SELECT id FROM facts
    WHERE entity_id = %s AND attribute = %s AND value = %s
    LIMIT 1
"""

_INSERT_CONFLICT = """
    INSERT INTO conflicts (fact_a_id, fact_b_id, status)
    VALUES (%s, %s, %s)
    ON CONFLICT DO NOTHING
"""

_WIPE_FACTS_FOR_ENTITIES = """
    DELETE FROM facts WHERE entity_id = ANY(%s::uuid[])
"""


def run() -> None:
    with get_conn() as conn:
        cur = conn.cursor()

        # Entities
        entity_ids: dict[str, str] = {}
        for ent in ENTITIES:
            cur.execute(
                _INSERT_ENTITY,
                (ent["type"], ent["name"], ent["canonical_name"]),
            )
            entity_ids[ent["name"]] = cur.fetchone()[0]
        print(f"  entities: {len(entity_ids)}")

        # Sources
        source_ids: dict[str, str] = {}
        for src in SOURCES:
            cur.execute(
                _INSERT_SOURCE,
                (src["type"], src["external_id"], json.dumps(src["raw_content"])),
            )
            source_ids[src["external_id"]] = cur.fetchone()[0]
        print(f"  sources:  {len(source_ids)}")

        # Wipe facts for these entities so re-runs are clean
        cur.execute(_WIPE_FACTS_FOR_ENTITIES, (list(entity_ids.values()),))

        # Facts (the canonical 50)
        fact_count = 0
        for ent_name, attr, val, src_ext, conf in FACTS:
            cur.execute(
                _INSERT_FACT,
                (
                    entity_ids[ent_name],
                    attr,
                    val,
                    source_ids.get(src_ext) if src_ext else None,
                    conf,
                ),
            )
            fact_count += 1

        # Conflict-generating facts (collide with existing facts)
        conflict_pairs: list[tuple[str, str, str]] = []  # (fact_a_id, fact_b_id, status)
        for ent_name, attr, val, src_ext, conf, collide_value in CONFLICT_FACTS:
            eid = entity_ids[ent_name]
            cur.execute(_FIND_FACT, (eid, attr, collide_value))
            existing = cur.fetchone()
            if existing is None:
                # Should not happen with our fixtures; skip defensively.
                continue
            cur.execute(
                _INSERT_FACT,
                (eid, attr, val, source_ids.get(src_ext), conf),
            )
            new_fact_id = cur.fetchone()[0]
            fact_count += 1

            # Determine status: whitespace/case-only diff -> auto_resolved
            status = (
                "auto_resolved"
                if val.strip().lower() == collide_value.strip().lower()
                else "open"
            )
            conflict_pairs.append((existing[0], new_fact_id, status))

        print(f"  facts:    {fact_count}")

        # Conflicts
        for fa, fb, status in conflict_pairs:
            cur.execute(_INSERT_CONFLICT, (fa, fb, status))
        print(f"  conflicts: {len(conflict_pairs)}")

        cur.close()


if __name__ == "__main__":
    print("Seeding DealBrain...")
    run()
    print("Done. Try: curl http://localhost:8000/entity/Acme%20Corp")
