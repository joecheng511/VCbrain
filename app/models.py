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


class EntityCore(BaseModel):
    id: str
    type: str
    name: str


class EntityResponse(BaseModel):
    entity: EntityCore
    facts: list[FactOut]
    conflicts: list[ConflictOut]
