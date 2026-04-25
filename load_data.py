"""
One-shot data loader — reads vcbrain_data/ JSON files and inserts into PostgreSQL.

Usage (from project root):
    py load_data.py

Skips if data is already present (checks entity count).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import settings

DATA            = Path(__file__).parent / "vcbrain_data"
COMPANIES_FILE  = DATA / "entities" / "companies.json"
CONFLICTS_FILE  = DATA / "conflicts" / "arr_conflicts.json"


def run():
    conn = psycopg2.connect(settings.database_url, cursor_factory=RealDictCursor)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ── guard: skip if already loaded ────────────────────────────────────
        cur.execute("SELECT COUNT(*) AS n FROM entities")
        if cur.fetchone()["n"] > 0:
            print("Database already contains data — skipping. "
                  "Run schema.sql again to reset, then re-run this script.")
            return

        # ── sources ───────────────────────────────────────────────────────────
        crm_id   = str(uuid.uuid4())
        email_id = str(uuid.uuid4())

        cur.execute("""
            INSERT INTO sources (id, type, external_id, raw_content)
            VALUES (%s, 'crm',   'clients.json', '{"file":"clients.json"}'::jsonb),
                   (%s, 'email', 'emails.json',  '{"file":"emails.json"}'::jsonb)
            ON CONFLICT (type, external_id) DO NOTHING
        """, (crm_id, email_id))

        cur.execute("SELECT id FROM sources WHERE type='crm'   AND external_id='clients.json'")
        crm_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM sources WHERE type='email' AND external_id='emails.json'")
        email_id = cur.fetchone()["id"]

        # ── companies ─────────────────────────────────────────────────────────
        with open(COMPANIES_FILE, encoding="utf-8") as f:
            companies = json.load(f)

        print(f"Inserting {len(companies)} companies…")
        entity_ids: dict[str, str] = {}   # name → uuid

        for co in companies:
            name = co["name"]
            eid  = str(uuid.uuid4())

            cur.execute("""
                INSERT INTO entities (id, type, name, canonical_name)
                VALUES (%s, 'Company', %s, lower(%s))
                ON CONFLICT (canonical_name, type) DO NOTHING
                RETURNING id
            """, (eid, name, name))
            row = cur.fetchone()

            if row:
                eid = row["id"]
            else:
                cur.execute(
                    "SELECT id FROM entities WHERE canonical_name=lower(%s) AND type='Company'",
                    (name,),
                )
                eid = cur.fetchone()["id"]

            entity_ids[name] = eid

            # Key facts from the CRM record
            fact_map = {
                "sector":          co.get("sector"),
                "stage":           co.get("stage"),
                "deal_status":     co.get("deal_status"),
                "poc_status":      co.get("poc_status"),
                "arr_eur":         co.get("arr_eur"),
                "mrr_eur":         co.get("mrr_eur"),
                "onboarding_date": co.get("onboarding_date"),
                "primary_contact": (co.get("primary_contact") or {}).get("name"),
            }
            for attr, val in fact_map.items():
                if val is None:
                    continue
                cur.execute("""
                    INSERT INTO facts (id, entity_id, attribute, value, source_id, confidence)
                    VALUES (%s, %s, %s, %s, %s, 0.90)
                """, (str(uuid.uuid4()), eid, attr, str(val), crm_id))

        print(f"  ✓ {len(entity_ids)} companies")

        # ── conflicts ─────────────────────────────────────────────────────────
        with open(CONFLICTS_FILE, encoding="utf-8") as f:
            conflicts = json.load(f)

        print(f"Inserting {len(conflicts)} ARR conflicts…")
        loaded = 0

        for c in conflicts:
            eid = entity_ids.get(c["entity_name"])
            if not eid:
                cur.execute(
                    "SELECT id FROM entities WHERE canonical_name=lower(%s) AND type='Company'",
                    (c["entity_name"],),
                )
                row = cur.fetchone()
                eid = row["id"] if row else None
            if not eid:
                continue

            fid_a, fid_b = str(uuid.uuid4()), str(uuid.uuid4())
            attr = c["attribute"]

            cur.execute("""
                INSERT INTO facts (id, entity_id, attribute, value, source_id, confidence)
                VALUES (%s, %s, %s, %s, %s, 0.90)
            """, (fid_a, eid, attr, str(c["value_a"]), crm_id))

            cur.execute("""
                INSERT INTO facts (id, entity_id, attribute, value, source_id, confidence)
                VALUES (%s, %s, %s, %s, %s, 0.72)
            """, (fid_b, eid, attr, str(c["value_b"]), email_id))

            cur.execute("""
                INSERT INTO conflicts (id, fact_a_id, fact_b_id, status)
                VALUES (%s, %s, %s, 'open')
                ON CONFLICT DO NOTHING
            """, (str(uuid.uuid4()), fid_a, fid_b))
            loaded += 1

        print(f"  ✓ {loaded} conflicts")

        conn.commit()
        print("\nDone — database loaded successfully. Restart the server and refresh the UI.")

    except Exception as exc:
        conn.rollback()
        print(f"\nERROR: {exc}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
