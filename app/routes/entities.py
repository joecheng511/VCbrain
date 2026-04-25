"""Entity and conflict read endpoints.

GET /entity/{name}  — locked contract for Node/TS partner; returns entity + facts + conflicts.
GET /conflicts      — list open conflicts; optional ?entity= filter by canonical name.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query

from ..db import get_dict_cursor
from ..models import ConflictListItem, ConflictOut, EntityCore, EntityListItem, EntityResponse, FactOut, ResolveRequest, SourceOut

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

_LIST_ENTITIES_SQL = """
    WITH entity_facts AS (
        SELECT
            entity_id,
            COUNT(*)                                                    AS fact_count,
            MAX(CASE WHEN attribute = 'sector'  THEN value END)         AS sector,
            MAX(CASE WHEN attribute = 'arr_eur' THEN value END)         AS arr_eur
        FROM facts
        GROUP BY entity_id
    ),
    entity_conflicts AS (
        SELECT entity_id, COUNT(DISTINCT conflict_id) AS conflict_count
        FROM (
            SELECT f.entity_id, c.id AS conflict_id
            FROM conflicts c JOIN facts f ON c.fact_a_id = f.id
            UNION ALL
            SELECT f.entity_id, c.id AS conflict_id
            FROM conflicts c JOIN facts f ON c.fact_b_id = f.id
        ) sides
        GROUP BY entity_id
    )
    SELECT
        e.id::text                          AS id,
        e.name,
        e.type::text                        AS type,
        COALESCE(ef.fact_count, 0)          AS fact_count,
        ef.sector,
        ef.arr_eur,
        COALESCE(ec.conflict_count, 0)      AS conflict_count
    FROM entities e
    LEFT JOIN entity_facts    ef ON ef.entity_id = e.id
    LEFT JOIN entity_conflicts ec ON ec.entity_id = e.id
    ORDER BY COALESCE(ef.fact_count, 0) DESC
    LIMIT %(limit)s
"""

_LIST_CONFLICTS_SQL = """
    SELECT
        c.id::text     AS conflict_id,
        e.name         AS entity_name,
        f1.attribute   AS attribute,
        f1.value       AS value_a,
        f2.value       AS value_b,
        s1.type        AS source_a,
        s2.type        AS source_b,
        c.status::text AS status
    FROM conflicts c
    JOIN facts f1 ON c.fact_a_id = f1.id
    JOIN facts f2 ON c.fact_b_id = f2.id
    JOIN entities e ON f1.entity_id = e.id
    LEFT JOIN sources s1 ON f1.source_id = s1.id
    LEFT JOIN sources s2 ON f2.source_id = s2.id
    WHERE (%(entity)s IS NULL OR e.canonical_name = lower(%(entity)s))
    ORDER BY c.created_at DESC
    LIMIT 500
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


@router.get("/entities", response_model=list[EntityListItem])
def list_entities(
    limit: int = Query(400, ge=1, le=500, description="Max entities to return"),
) -> list[EntityListItem]:
    """Return all entities with summary stats for graph rendering."""
    with get_dict_cursor() as cur:
        cur.execute(_LIST_ENTITIES_SQL, {"limit": limit})
        rows = cur.fetchall()

    return [
        EntityListItem(
            id=r["id"],
            name=r["name"],
            type=r["type"],
            fact_count=int(r["fact_count"] or 0),
            sector=r["sector"],
            arr_eur=float(r["arr_eur"]) if r["arr_eur"] is not None else None,
            conflict_count=int(r["conflict_count"] or 0),
        )
        for r in rows
    ]


@router.get("/conflicts", response_model=list[ConflictListItem])
def list_conflicts(
    entity: Optional[str] = Query(None, description="Filter by entity canonical name (case-insensitive)"),
) -> list[ConflictListItem]:
    """Return all conflicts, optionally filtered to a single entity by name."""
    with get_dict_cursor() as cur:
        cur.execute(_LIST_CONFLICTS_SQL, {"entity": entity})
        rows = cur.fetchall()

    return [
        ConflictListItem(
            conflict_id=r["conflict_id"],
            entity_name=r["entity_name"],
            attribute=r["attribute"],
            value_a=r["value_a"],
            value_b=r["value_b"],
            source_a=r["source_a"],
            source_b=r["source_b"],
            status=r["status"],
        )
        for r in rows
    ]


@router.patch("/conflicts/{conflict_id}/resolve", tags=["conflicts"])
def resolve_conflict(
    conflict_id: str,
    body: ResolveRequest = Body(default=ResolveRequest()),
) -> dict[str, str]:
    """Mark a conflict as resolved.  resolution must be 'human_resolved' or 'auto_resolved'."""
    allowed = {"human_resolved", "auto_resolved"}
    if body.resolution not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"resolution must be one of {sorted(allowed)}",
        )
    with get_dict_cursor() as cur:
        cur.execute(
            """
            UPDATE conflicts
               SET status = %(status)s::conflict_status
             WHERE id = %(id)s::uuid
            RETURNING id::text
            """,
            {"status": body.resolution, "id": conflict_id},
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Conflict '{conflict_id}' not found")
    return {"conflict_id": row["id"], "status": body.resolution}


@router.get("/entities/count", tags=["entities"])
def count_entities() -> dict[str, int]:
    """Return total entity count and fact count."""
    with get_dict_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM entities")
        entities_n = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM facts")
        facts_n = int(cur.fetchone()["n"])
    return {"count": entities_n, "fact_count": facts_n}
