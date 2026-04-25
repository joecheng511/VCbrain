"""GET /entity/{name} — the one endpoint our partner consumes.

Lookup is case-insensitive on canonical_name. Returns 404 if no match.
Response shape is locked: { entity, facts[], conflicts[] }.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_dict_cursor
from ..models import ConflictOut, EntityCore, EntityResponse, FactOut, SourceOut

router = APIRouter()


_FIND_ENTITY_SQL = """
    SELECT id, type, name
    FROM entities
    WHERE canonical_name = lower(%(name)s)
    ORDER BY created_at ASC
    LIMIT 1
"""

_FACTS_SQL = """
    SELECT
        f.attribute,
        f.value,
        f.confidence,
        s.type        AS source_type,
        s.external_id AS source_external_id
    FROM facts f
    LEFT JOIN sources s ON f.source_id = s.id
    WHERE f.entity_id = %(eid)s
    ORDER BY f.confidence DESC, f.attribute ASC
"""

_CONFLICTS_SQL = """
    SELECT
        f1.attribute   AS attribute,
        f1.value       AS value_a,
        f2.value       AS value_b,
        c.status::text AS status
    FROM conflicts c
    JOIN facts f1 ON c.fact_a_id = f1.id
    JOIN facts f2 ON c.fact_b_id = f2.id
    WHERE f1.entity_id = %(eid)s OR f2.entity_id = %(eid)s
    ORDER BY c.created_at DESC
"""


@router.get("/entity/{name}", response_model=EntityResponse)
def get_entity(name: str) -> EntityResponse:
    with get_dict_cursor() as cur:
        cur.execute(_FIND_ENTITY_SQL, {"name": name})
        ent_row = cur.fetchone()
        if ent_row is None:
            raise HTTPException(status_code=404, detail=f"Entity '{name}' not found")

        eid = ent_row["id"]

        cur.execute(_FACTS_SQL, {"eid": eid})
        fact_rows = cur.fetchall()

        cur.execute(_CONFLICTS_SQL, {"eid": eid})
        conflict_rows = cur.fetchall()

    facts = [
        FactOut(
            attribute=r["attribute"],
            value=r["value"],
            confidence=float(r["confidence"]),
            source=(
                SourceOut(type=r["source_type"], external_id=r["source_external_id"])
                if r["source_type"] is not None
                else None
            ),
        )
        for r in fact_rows
    ]

    conflicts = [
        ConflictOut(
            attribute=r["attribute"],
            value_a=r["value_a"],
            value_b=r["value_b"],
            status=r["status"],
        )
        for r in conflict_rows
    ]

    return EntityResponse(
        entity=EntityCore(
            id=str(ent_row["id"]),
            type=str(ent_row["type"]),
            name=ent_row["name"],
        ),
        facts=facts,
        conflicts=conflicts,
    )
