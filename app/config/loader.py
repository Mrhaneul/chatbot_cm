"""
app/config/loader.py

Loads and validates all YAML config files at import time.
Exports typed constants consumed by app/main.py and app/rag/metadata_filtering.py.

Raises ConfigLoadError at startup for any missing file, YAML parse error,
or schema violation so the server never starts with broken config.

Validation functions (_load_yaml, _validate_platforms, _validate_intents,
_validate_routing, _validate_clarification) are exported so tests can call them
directly with synthetic data without re-importing the module.
"""
from __future__ import annotations

from pathlib import Path

import yaml


# ── Custom exception ──────────────────────────────────────────────────────────

class ConfigLoadError(ValueError):
    """Raised when a config file is missing, malformed, or fails schema validation."""


# ── Low-level YAML loader ─────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    """Load and parse a YAML file. Raises ConfigLoadError for any problem."""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigLoadError(f"{path}: file not found") from None
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"{path}: YAML parse error -- {exc}") from None


# ── Schema validators ─────────────────────────────────────────────────────────

def _validate_platforms(path: Path, raw: dict) -> list[dict]:
    """
    Validate platforms config.  Returns the validated platform list.
    path is used only in error messages; it need not exist on disk.
    """
    platforms = raw.get("platforms", [])
    if not platforms:
        raise ConfigLoadError(f"{path}: 'platforms' list is empty or missing")

    for p in platforms:
        _label = p.get("key", "<unknown>")
        for field in ("key", "rag_key", "display_name", "aliases"):
            if field not in p:
                raise ConfigLoadError(
                    f"{path}: platform '{_label}' is missing required field '{field}'"
                )
        if not isinstance(p["aliases"], list) or not p["aliases"]:
            raise ConfigLoadError(
                f"{path}: platform '{p['key']}' field 'aliases' must be a non-empty list"
            )
        if p.get("publisher_list_position") is not None:
            if not p.get("publisher_list_label"):
                raise ConfigLoadError(
                    f"{path}: platform '{p['key']}' has 'publisher_list_position'"
                    f" but is missing required field 'publisher_list_label'"
                )

    return platforms


def _validate_routing(path: Path, raw: dict) -> dict:
    """Validate routing config. Returns the raw dict on success."""
    greeting = raw.get("greeting", {})
    if not greeting.get("keywords"):
        raise ConfigLoadError(f"{path}: 'greeting.keywords' is missing or empty")
    if not (greeting.get("reply") or "").strip():
        raise ConfigLoadError(f"{path}: 'greeting.reply' is missing or empty")
    return raw


def _validate_clarification(path: Path, raw: dict) -> dict:
    """Validate clarification_flows config. Returns the raw dict on success."""
    msg = (raw.get("platform_clarification", {}).get("message") or "").strip()
    if not msg:
        raise ConfigLoadError(
            f"{path}: 'platform_clarification.message' is missing or empty"
        )
    return raw


def _validate_intents(path: Path, raw: dict) -> dict:
    """Validate intents config. Returns the raw dict on success."""
    for section in ("ia_keywords", "opt_out_policy_signals", "informational_patterns"):
        if not raw.get(section):
            raise ConfigLoadError(
                f"{path}: required section '{section}' is missing or empty"
            )
    return raw


# ── Config directory ──────────────────────────────────────────────────────────

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


# ── platforms.yaml ────────────────────────────────────────────────────────────

_platforms_path = _CONFIG_DIR / "platforms.yaml"
_platform_list: list[dict] = _validate_platforms(
    _platforms_path, _load_yaml(_platforms_path)
)

# Main.py routing dict: UPPERCASE_KEY -> list[str]
PLATFORM_ALIASES: dict[str, list[str]] = {
    p["key"]: list(p["aliases"]) for p in _platform_list
}

# Human-readable names
PLATFORM_DISPLAY_NAMES: dict[str, str] = {
    p["key"]: p["display_name"] for p in _platform_list
}

# FAISS index key overrides (e.g. VITALSOURCE shares Bedford's index)
PLATFORM_RETRIEVAL_KEY: dict[str, str] = {
    p["key"]: p["retrieval_key"]
    for p in _platform_list
    if p.get("retrieval_key")
}

# Numbered publisher list sent when platform is unrecognized
_platforms_in_list = sorted(
    [p for p in _platform_list if p.get("publisher_list_position") is not None],
    key=lambda p: p["publisher_list_position"],
)
PUBLISHER_LIST_TEXT: str = "\n".join(
    f"{p['publisher_list_position']}. {p['publisher_list_label']}"
    for p in _platforms_in_list
)
# Maps numeric answer ("1"-"12") to the rag_key for retrieval
PUBLISHER_LIST_MAP: dict[str, str] = {
    str(p["publisher_list_position"]): p["rag_key"]
    for p in _platforms_in_list
}

# Tuple-of-tuples consumed by metadata_filtering.py: (metadata_key, (alias, ...))
# Only platforms with metadata_aliases are included; order matches original.
METADATA_PLATFORM_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (
        p.get("metadata_key", p["key"].lower()),
        tuple(p["metadata_aliases"]),
    )
    for p in _platform_list
    if p.get("metadata_aliases")
)

# API response shape: {key, display_name, keywords}
# Uses rag_key (lowercase) as key and aliases as keywords to match the
# existing /platforms API contract previously served from app/rag/platforms.yaml.
PLATFORMS_FOR_API: list[dict] = [
    {
        "key": p["rag_key"],
        "display_name": p["display_name"],
        "keywords": list(p["aliases"]),
    }
    for p in _platform_list
]


# ── routing.yaml ──────────────────────────────────────────────────────────────

_routing_path = _CONFIG_DIR / "routing.yaml"
_routing_raw = _validate_routing(_routing_path, _load_yaml(_routing_path))
_greeting = _routing_raw.get("greeting", {})

GREETING_KEYWORDS: list[str] = _greeting.get("keywords", [])
GREETING_REPLY: str = (_greeting.get("reply") or "").strip()


# ── clarification_flows.yaml ──────────────────────────────────────────────────

_clarification_path = _CONFIG_DIR / "clarification_flows.yaml"
_clarification_raw = _validate_clarification(
    _clarification_path, _load_yaml(_clarification_path)
)
PLATFORM_CLARIFICATION_MESSAGE: str = (
    _clarification_raw.get("platform_clarification", {}).get("message") or ""
).strip()


# ── intents.yaml ──────────────────────────────────────────────────────────────

_intents_path = _CONFIG_DIR / "intents.yaml"
_intents_raw = _validate_intents(_intents_path, _load_yaml(_intents_path))

IA_KEYWORDS: list[str] = _intents_raw.get("ia_keywords", [])
OPT_OUT_POLICY_SIGNALS: list[str] = _intents_raw.get("opt_out_policy_signals", [])
OPT_OUT_TROUBLESHOOTING_EXCLUSIONS: list[str] = _intents_raw.get(
    "opt_out_troubleshooting_exclusions", []
)
INFORMATIONAL_PATTERNS: list[str] = _intents_raw.get("informational_patterns", [])
