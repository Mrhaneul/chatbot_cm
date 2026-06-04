"""
app/intake/models.py

IntakeProfile: lightweight dataclass that tracks per-session slot state.
Stored in session["intake_profile"] as a plain dict via to_dict() / from_dict().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IntakeProfile:
    platform: Optional[str] = None          # uppercase key, e.g. "CENGAGE"
    issue_type: Optional[str] = None        # e.g. "access", "missing", "account"
    material_type: Optional[str] = None     # e.g. "textbook", "workbook"
    course_code: Optional[str] = None       # e.g. "CS101"
    turns_spent: int = 0
    original_message: str = ""

    _MAX_TURNS: int = field(default=3, init=False, repr=False, compare=False)

    def is_complete(self) -> bool:
        return bool(self.platform and self.issue_type)

    def is_expired(self) -> bool:
        return self.turns_spent >= self._MAX_TURNS

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "issue_type": self.issue_type,
            "material_type": self.material_type,
            "course_code": self.course_code,
            "turns_spent": self.turns_spent,
            "original_message": self.original_message,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IntakeProfile":
        return cls(
            platform=d.get("platform"),
            issue_type=d.get("issue_type"),
            material_type=d.get("material_type"),
            course_code=d.get("course_code"),
            turns_spent=d.get("turns_spent", 0),
            original_message=d.get("original_message", ""),
        )

    def build_enriched_query(self, display_names: dict[str, str]) -> str:
        parts = [self.original_message]
        if self.platform and self.platform in display_names:
            parts.append(f"Platform: {display_names[self.platform]}")
        if self.issue_type:
            parts.append(f"Issue: {self.issue_type}")
        if self.material_type:
            parts.append(f"Material: {self.material_type}")
        if self.course_code:
            parts.append(f"Course: {self.course_code}")
        return ". ".join(parts)
