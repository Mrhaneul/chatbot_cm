"""
Tests for app/config/loader.py.

Verifies that all four YAML config files load correctly and export
well-formed typed constants, and that the validator functions raise
ConfigLoadError with useful messages for all invalid inputs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import (
    ConfigLoadError,
    GREETING_KEYWORDS,
    GREETING_REPLY,
    IA_KEYWORDS,
    INFORMATIONAL_PATTERNS,
    METADATA_PLATFORM_ALIASES,
    OPT_OUT_POLICY_SIGNALS,
    OPT_OUT_TROUBLESHOOTING_EXCLUSIONS,
    PLATFORM_ALIASES,
    PLATFORM_CLARIFICATION_MESSAGE,
    PLATFORM_DISPLAY_NAMES,
    PLATFORM_RETRIEVAL_KEY,
    PLATFORMS_FOR_API,
    PUBLISHER_LIST_MAP,
    PUBLISHER_LIST_TEXT,
    _load_yaml,
    _validate_clarification,
    _validate_intents,
    _validate_platforms,
    _validate_routing,
)

# ── Smoke: all imports succeed ────────────────────────────────────────────────

def test_imports_succeed():
    assert PLATFORM_ALIASES is not None


# ── Platform coverage ─────────────────────────────────────────────────────────

_ALL_PLATFORM_KEYS = [
    "CENGAGE", "MCGRAW_HILL", "PEARSON", "WILEY", "MACMILLAN",
    "SAGE", "BEDFORD", "CLIFTON", "SIMUCASE", "ZYBOOKS",
    "STUKENT", "VITALSOURCE", "INQUIZITIVE",
]

@pytest.mark.parametrize("key", _ALL_PLATFORM_KEYS)
def test_platform_aliases_has_all_keys(key):
    assert key in PLATFORM_ALIASES, f"PLATFORM_ALIASES missing key: {key}"

@pytest.mark.parametrize("key", _ALL_PLATFORM_KEYS)
def test_platform_display_names_has_all_keys(key):
    assert key in PLATFORM_DISPLAY_NAMES, f"PLATFORM_DISPLAY_NAMES missing key: {key}"

@pytest.mark.parametrize("key", _ALL_PLATFORM_KEYS)
def test_platform_aliases_non_empty(key):
    assert len(PLATFORM_ALIASES[key]) >= 1, f"PLATFORM_ALIASES[{key}] is empty"

def test_total_platform_count():
    assert len(PLATFORM_ALIASES) == 13


# ── Alias spot-checks ─────────────────────────────────────────────────────────

def test_cengage_aliases_include_mindtap():
    assert "mindtap" in PLATFORM_ALIASES["CENGAGE"]

def test_mcgraw_hill_aliases_include_connect():
    assert "connect" in PLATFORM_ALIASES["MCGRAW_HILL"]

def test_inquizitive_aliases_include_norton():
    assert "norton" in PLATFORM_ALIASES["INQUIZITIVE"]

def test_vitalsource_aliases_contain_vitalsource():
    assert "vitalsource" in PLATFORM_ALIASES["VITALSOURCE"]

def test_clifton_aliases_include_cliftonstrengths():
    assert "cliftonstrengths" in PLATFORM_ALIASES["CLIFTON"]


# ── PLATFORM_RETRIEVAL_KEY ────────────────────────────────────────────────────

def test_vitalsource_retrieval_key_is_bedford():
    assert PLATFORM_RETRIEVAL_KEY.get("VITALSOURCE") == "bedford"


# ── Publisher list ────────────────────────────────────────────────────────────

def test_publisher_list_text_has_twelve_entries():
    lines = [l for l in PUBLISHER_LIST_TEXT.splitlines() if l.strip()]
    assert len(lines) == 12

def test_publisher_list_text_format():
    for line in PUBLISHER_LIST_TEXT.splitlines():
        if line.strip():
            num, _, label = line.partition(". ")
            assert num.isdigit(), f"Expected digit prefix in: {line!r}"
            assert label.strip(), f"Empty label in: {line!r}"

def test_publisher_list_map_maps_one_through_twelve():
    assert set(PUBLISHER_LIST_MAP.keys()) == {str(i) for i in range(1, 13)}

def test_publisher_list_map_value_for_mcgraw():
    assert PUBLISHER_LIST_MAP["5"] == "mcgraw"

def test_publisher_list_map_value_for_bedford():
    assert PUBLISHER_LIST_MAP["1"] == "bedford"

def test_publisher_list_map_value_for_inquizitive():
    assert PUBLISHER_LIST_MAP["4"] == "inquizitive"


# ── PLATFORMS_FOR_API ─────────────────────────────────────────────────────────

def test_platforms_for_api_is_list():
    assert isinstance(PLATFORMS_FOR_API, list)
    assert len(PLATFORMS_FOR_API) == 13

def test_platforms_for_api_entry_has_required_fields():
    for entry in PLATFORMS_FOR_API:
        assert "key" in entry, f"Missing 'key' in: {entry}"
        assert "display_name" in entry, f"Missing 'display_name' in: {entry}"
        assert "keywords" in entry, f"Missing 'keywords' in: {entry}"
        assert isinstance(entry["keywords"], list), "keywords must be a list"

def test_platforms_for_api_uses_lowercase_rag_keys():
    keys = {e["key"] for e in PLATFORMS_FOR_API}
    assert "cengage" in keys
    assert "mcgraw" in keys


# ── METADATA_PLATFORM_ALIASES ─────────────────────────────────────────────────

_EXPECTED_METADATA_KEYS = {
    "mcgraw_hill", "vitalsource", "bedford", "pearson", "cengage",
    "wiley", "zybooks", "sage", "macmillan", "simucase", "cliftonstrengths",
}

def test_metadata_platform_aliases_is_tuple():
    assert isinstance(METADATA_PLATFORM_ALIASES, tuple)

def test_metadata_platform_aliases_keys_match_original():
    actual = {key for key, _ in METADATA_PLATFORM_ALIASES}
    assert actual == _EXPECTED_METADATA_KEYS

def test_metadata_platform_aliases_mcgraw_hill_aliases():
    aliases = dict(METADATA_PLATFORM_ALIASES).get("mcgraw_hill", ())
    assert "mcgraw hill" in aliases
    assert "connect" in aliases

def test_metadata_platform_aliases_stukent_not_present():
    keys = {k for k, _ in METADATA_PLATFORM_ALIASES}
    assert "stukent" not in keys

def test_metadata_platform_aliases_inquizitive_not_present():
    keys = {k for k, _ in METADATA_PLATFORM_ALIASES}
    assert "inquizitive" not in keys

def test_metadata_platform_aliases_clifton_key_is_cliftonstrengths():
    keys = {k for k, _ in METADATA_PLATFORM_ALIASES}
    assert "cliftonstrengths" in keys
    assert "clifton" not in keys


# ── Greeting config ───────────────────────────────────────────────────────────

def test_greeting_keywords_contains_hi():
    assert "hi" in GREETING_KEYWORDS

def test_greeting_keywords_contains_hello():
    assert "hello" in GREETING_KEYWORDS

def test_greeting_reply_mentions_lance():
    assert "Lance" in GREETING_REPLY

def test_greeting_reply_is_str():
    assert isinstance(GREETING_REPLY, str) and len(GREETING_REPLY) > 0


# ── Clarification message ─────────────────────────────────────────────────────

def test_platform_clarification_message_non_empty():
    assert isinstance(PLATFORM_CLARIFICATION_MESSAGE, str)
    assert len(PLATFORM_CLARIFICATION_MESSAGE) > 0

def test_platform_clarification_mentions_cengage():
    assert "Cengage" in PLATFORM_CLARIFICATION_MESSAGE


# ── Intent keyword lists ──────────────────────────────────────────────────────

def test_ia_keywords_contains_cannot_access():
    assert "cannot access" in IA_KEYWORDS

def test_ia_keywords_contains_access():
    assert "access" in IA_KEYWORDS

def test_opt_out_policy_signals_contains_opt_out():
    assert "opt out" in OPT_OUT_POLICY_SIGNALS

def test_opt_out_troubleshooting_exclusions_contains_cannot_access():
    assert "cannot access" in OPT_OUT_TROUBLESHOOTING_EXCLUSIONS

def test_informational_patterns_contains_what_is():
    assert "what is" in INFORMATIONAL_PATTERNS

def test_informational_patterns_contains_how_does():
    assert "how does" in INFORMATIONAL_PATTERNS


# ============================================================================
# Failure / validation tests
# These call the exported validator functions directly with synthetic data
# so no module re-import or file I/O against real config is needed.
# ============================================================================

class TestLoadYamlFailures:
    """_load_yaml raises ConfigLoadError for missing or malformed files.

    Avoids tmp_path because of a pre-existing Windows PermissionError on
    C:\\Users\\CMInter1\\AppData\\Local\\Temp\\pytest-of-CMInter1 (WinError 5).
    Uses a hardcoded nonexistent path for file-not-found tests and monkeypatch
    for the parse-error test.
    """

    def test_file_not_found_raises_config_load_error(self):
        nonexistent = Path("C:/no/such/path/does_not_exist_abc123.yaml")
        with pytest.raises(ConfigLoadError, match="file not found"):
            _load_yaml(nonexistent)

    def test_malformed_yaml_raises_config_load_error(self, monkeypatch):
        from unittest.mock import mock_open
        bad_yaml = "platforms:\n  - key: foo\n    aliases: [\n"
        monkeypatch.setattr("builtins.open", mock_open(read_data=bad_yaml))
        with pytest.raises(ConfigLoadError, match="YAML parse error"):
            _load_yaml(Path("fake_platforms.yaml"))

    def test_error_message_includes_file_path(self):
        unique = Path("C:/no/such/path/my_unique_config_xyz789.yaml")
        with pytest.raises(ConfigLoadError, match="my_unique_config_xyz789"):
            _load_yaml(unique)


class TestValidatePlatformsFailures:
    """_validate_platforms raises ConfigLoadError for schema violations."""

    def _path(self) -> Path:
        return Path("config/platforms.yaml")

    def test_empty_platforms_list_raises(self):
        with pytest.raises(ConfigLoadError, match="'platforms' list is empty"):
            _validate_platforms(self._path(), {"platforms": []})

    def test_missing_platforms_key_raises(self):
        with pytest.raises(ConfigLoadError, match="'platforms' list is empty"):
            _validate_platforms(self._path(), {})

    def test_missing_required_field_key(self):
        data = {"platforms": [
            {"rag_key": "cengage", "display_name": "Cengage", "aliases": ["cengage"]}
        ]}
        with pytest.raises(ConfigLoadError, match="missing required field 'key'"):
            _validate_platforms(self._path(), data)

    def test_missing_required_field_rag_key(self):
        data = {"platforms": [
            {"key": "CENGAGE", "display_name": "Cengage", "aliases": ["cengage"]}
        ]}
        with pytest.raises(ConfigLoadError, match="missing required field 'rag_key'"):
            _validate_platforms(self._path(), data)

    def test_missing_required_field_display_name(self):
        data = {"platforms": [
            {"key": "CENGAGE", "rag_key": "cengage", "aliases": ["cengage"]}
        ]}
        with pytest.raises(ConfigLoadError, match="missing required field 'display_name'"):
            _validate_platforms(self._path(), data)

    def test_missing_required_field_aliases(self):
        data = {"platforms": [
            {"key": "CENGAGE", "rag_key": "cengage", "display_name": "Cengage"}
        ]}
        with pytest.raises(ConfigLoadError, match="missing required field 'aliases'"):
            _validate_platforms(self._path(), data)

    def test_aliases_is_string_not_list(self):
        data = {"platforms": [
            {"key": "CENGAGE", "rag_key": "cengage", "display_name": "Cengage",
             "aliases": "cengage"}
        ]}
        with pytest.raises(ConfigLoadError, match="non-empty list"):
            _validate_platforms(self._path(), data)

    def test_aliases_is_empty_list(self):
        data = {"platforms": [
            {"key": "CENGAGE", "rag_key": "cengage", "display_name": "Cengage",
             "aliases": []}
        ]}
        with pytest.raises(ConfigLoadError, match="non-empty list"):
            _validate_platforms(self._path(), data)

    def test_publisher_list_position_without_label_raises(self):
        data = {"platforms": [
            {"key": "CENGAGE", "rag_key": "cengage", "display_name": "Cengage",
             "aliases": ["cengage"], "publisher_list_position": 3}
        ]}
        with pytest.raises(ConfigLoadError, match="publisher_list_label"):
            _validate_platforms(self._path(), data)

    def test_publisher_list_position_with_empty_label_raises(self):
        data = {"platforms": [
            {"key": "CENGAGE", "rag_key": "cengage", "display_name": "Cengage",
             "aliases": ["cengage"], "publisher_list_position": 3,
             "publisher_list_label": ""}
        ]}
        with pytest.raises(ConfigLoadError, match="publisher_list_label"):
            _validate_platforms(self._path(), data)

    def test_error_message_includes_platform_key(self):
        data = {"platforms": [
            {"key": "MY_PLATFORM", "rag_key": "foo", "display_name": "Foo",
             "aliases": "not-a-list"}
        ]}
        with pytest.raises(ConfigLoadError, match="MY_PLATFORM"):
            _validate_platforms(self._path(), data)

    def test_valid_platform_without_publisher_list_passes(self):
        data = {"platforms": [
            {"key": "CLIFTON", "rag_key": "clifton", "display_name": "CliftonStrengths",
             "aliases": ["clifton"]}
        ]}
        result = _validate_platforms(self._path(), data)
        assert len(result) == 1


class TestValidateIntentsFailures:
    """_validate_intents raises ConfigLoadError for missing required sections."""

    def _path(self) -> Path:
        return Path("config/intents.yaml")

    def test_missing_ia_keywords_raises(self):
        data = {"opt_out_policy_signals": ["opt out"], "informational_patterns": ["what is"]}
        with pytest.raises(ConfigLoadError, match="ia_keywords"):
            _validate_intents(self._path(), data)

    def test_empty_ia_keywords_raises(self):
        data = {"ia_keywords": [], "opt_out_policy_signals": ["opt out"],
                "informational_patterns": ["what is"]}
        with pytest.raises(ConfigLoadError, match="ia_keywords"):
            _validate_intents(self._path(), data)

    def test_missing_opt_out_signals_raises(self):
        data = {"ia_keywords": ["access"], "informational_patterns": ["what is"]}
        with pytest.raises(ConfigLoadError, match="opt_out_policy_signals"):
            _validate_intents(self._path(), data)

    def test_missing_informational_patterns_raises(self):
        data = {"ia_keywords": ["access"], "opt_out_policy_signals": ["opt out"]}
        with pytest.raises(ConfigLoadError, match="informational_patterns"):
            _validate_intents(self._path(), data)

    def test_valid_intents_config_passes(self):
        data = {
            "ia_keywords": ["access"],
            "opt_out_policy_signals": ["opt out"],
            "informational_patterns": ["what is"],
        }
        result = _validate_intents(self._path(), data)
        assert result is data


class TestValidateRoutingFailures:
    """_validate_routing raises ConfigLoadError for missing greeting config."""

    def _path(self) -> Path:
        return Path("config/routing.yaml")

    def test_missing_greeting_keywords_raises(self):
        data = {"greeting": {"reply": "Hello!"}}
        with pytest.raises(ConfigLoadError, match="greeting.keywords"):
            _validate_routing(self._path(), data)

    def test_missing_greeting_reply_raises(self):
        data = {"greeting": {"keywords": ["hi"]}}
        with pytest.raises(ConfigLoadError, match="greeting.reply"):
            _validate_routing(self._path(), data)


class TestValidateClarificationFailures:
    """_validate_clarification raises ConfigLoadError for missing message."""

    def _path(self) -> Path:
        return Path("config/clarification_flows.yaml")

    def test_missing_platform_clarification_message_raises(self):
        with pytest.raises(ConfigLoadError, match="platform_clarification.message"):
            _validate_clarification(self._path(), {})

    def test_empty_message_raises(self):
        data = {"platform_clarification": {"message": ""}}
        with pytest.raises(ConfigLoadError, match="platform_clarification.message"):
            _validate_clarification(self._path(), data)
