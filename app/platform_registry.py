"""
Dynamic platform/pdf registry shared by runtime and tooling.

This lets add_instruction.py register new platforms and mappings without
manually editing application source files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "data" / "platform_registry.json"


DEFAULT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "platform_aliases": {},
    "platform_display_names": {},
    "platform_normalization": {},
    "platform_priority": {},
    "txt_to_pdf_map": {},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            merged = dict(out[key])
            merged.update(value)
            out[key] = merged
        else:
            out[key] = value
    return out


def load_registry() -> Dict[str, Dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return dict(DEFAULT_REGISTRY)

    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT_REGISTRY)
        return _deep_merge(DEFAULT_REGISTRY, data)
    except Exception:
        return dict(DEFAULT_REGISTRY)


def save_registry(registry: Dict[str, Dict[str, Any]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=True), encoding="utf-8")


def canonical_platform_key(value: str) -> str:
    key = value.strip().lower().replace(" ", "_")
    key = "_".join(part for part in key.split("_") if part)
    return key


def internal_platform_key(platform_key: str) -> str:
    """
    Convert registry platform key to internal app platform key.
    """
    p = canonical_platform_key(platform_key)
    special = {
        "mcgrawhill": "MCGRAW_HILL",
        "mcgraw_hill": "MCGRAW_HILL",
    }
    if p in special:
        return special[p]
    return p.upper()
