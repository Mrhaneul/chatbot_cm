"""
app/intake/planner_models.py

Pydantic model for the structured decision returned by the LLM intake planner.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class IntakePlannerDecision(BaseModel):
    action: Literal["ALLOW_RAG", "ASK_CLARIFICATION"]
    intent: str
    confidence: float
    known_slots: dict[str, str]
    missing_slots: list[str]
    next_question_key: Optional[str] = None
    enriched_query: Optional[str] = None
