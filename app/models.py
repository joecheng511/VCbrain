"""Pydantic response models. Shape is part of our public contract with the
Node/TS API consumer — do not change keys without coordinating."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SourceOut(BaseModel):
    type: str
    external_id: str


class FactOut(BaseModel):
    attribute: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: Optional[SourceOut] = None


class ConflictOut(BaseModel):
    attribute: str
    value_a: str
    value_b: str
    status: str


class EntityListItem(BaseModel):
    """Lightweight entity record for graph/list views."""
    id: str
    name: str
    type: str
    fact_count: int = 0
    sector: Optional[str] = None
    arr_eur: Optional[float] = None
    conflict_count: int = 0


class ConflictListItem(BaseModel):
    """Extended conflict record returned by GET /conflicts (includes entity name and sources)."""
    conflict_id: str
    entity_name: str
    attribute: str
    value_a: str
    value_b: str
    source_a: Optional[str] = None
    source_b: Optional[str] = None
    status: str


class ResolveRequest(BaseModel):
    """Body for PATCH /conflicts/{id}/resolve."""
    resolution: str = Field(
        "human_resolved",
        description="One of: human_resolved, auto_resolved",
    )


class EntityCore(BaseModel):
    id: str
    type: str
    name: str


class EntityResponse(BaseModel):
    entity: EntityCore
    facts: list[FactOut]
    conflicts: list[ConflictOut]
