"""
tests/test_intake.py

Unit tests for the Phase 3 intake / slot-filling module.
Covers: models, slot_extractor, questions, flow, and multi-turn lifecycle.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.intake.models import IntakeProfile
from app.intake.questions import VAGUE_PATTERN_RE, NEXT_QUESTION, INTAKE_FALLBACK_MESSAGE
from app.intake.slot_extractor import (
    extract_platform,
    extract_issue_type,
    extract_course_code,
    extract_material_type,
)
from app.intake.flow import (
    is_vague_message,
    should_enter_intake,
    update_profile,
    next_question as intake_next_question,
    intake_is_complete,
    intake_fallback_message,
    is_unknown_answer,
    INTAKE_ESCALATION_MESSAGE,
    MAX_UNKNOWN_ATTEMPTS,
)
from app.intake.planner_models import IntakePlannerDecision
from app.intake.question_templates import QUESTION_TEMPLATES, FALLBACK_QUESTION, QUESTION_KEY_TO_SLOT
from app.intake.llm_planner import (
    should_run_planner,
    get_question_for_decision,
    run_intake_planner,
    INTAKE_PLANNER_MODEL,
    INTAKE_PLANNER_FALLBACK_MODEL,
    _PLANNER_MAX_TOKENS,
)


# ── IntakeProfile ─────────────────────────────────────────────────────────────

class TestIntakeProfileBasics:
    def test_empty_profile_not_complete(self):
        p = IntakeProfile()
        assert not p.is_complete()

    def test_platform_only_not_complete(self):
        p = IntakeProfile(platform="CENGAGE")
        assert not p.is_complete()

    def test_issue_type_only_not_complete(self):
        p = IntakeProfile(issue_type="access")
        assert not p.is_complete()

    def test_both_slots_complete(self):
        p = IntakeProfile(platform="CENGAGE", issue_type="access")
        assert p.is_complete()

    def test_not_expired_at_zero(self):
        p = IntakeProfile(turns_spent=0)
        assert not p.is_expired()

    def test_expired_at_max_turns(self):
        p = IntakeProfile(turns_spent=3)
        assert p.is_expired()

    def test_not_expired_below_max(self):
        p = IntakeProfile(turns_spent=2)
        assert not p.is_expired()


class TestIntakeProfileRoundtrip:
    def test_roundtrip_empty(self):
        p = IntakeProfile()
        assert IntakeProfile.from_dict(p.to_dict()) == p

    def test_roundtrip_full(self):
        p = IntakeProfile(
            platform="VITALSOURCE",
            issue_type="missing",
            material_type="textbook",
            course_code="ENGL1301",
            turns_spent=2,
            original_message="my book is gone",
        )
        assert IntakeProfile.from_dict(p.to_dict()) == p

    def test_from_dict_missing_keys(self):
        p = IntakeProfile.from_dict({})
        assert p.platform is None
        assert p.turns_spent == 0


class TestBuildEnrichedQuery:
    _DISPLAY = {"CENGAGE": "Cengage MindTap", "VITALSOURCE": "VitalSource"}

    def test_just_original_message_when_no_slots(self):
        p = IntakeProfile(original_message="help me")
        result = p.build_enriched_query(self._DISPLAY)
        assert result == "help me"

    def test_includes_platform_display_name(self):
        p = IntakeProfile(original_message="my book", platform="CENGAGE")
        result = p.build_enriched_query(self._DISPLAY)
        assert "Cengage MindTap" in result

    def test_includes_issue_type(self):
        p = IntakeProfile(original_message="help", issue_type="access")
        result = p.build_enriched_query(self._DISPLAY)
        assert "access" in result

    def test_includes_course_code(self):
        p = IntakeProfile(original_message="help", course_code="CS101")
        result = p.build_enriched_query(self._DISPLAY)
        assert "CS101" in result

    def test_unknown_platform_key_skipped(self):
        p = IntakeProfile(original_message="help", platform="UNKNOWN_KEY")
        result = p.build_enriched_query(self._DISPLAY)
        assert "UNKNOWN_KEY" not in result


# ── VaguePatternRegex ─────────────────────────────────────────────────────────

class TestVaguePatternRegex:
    def _match(self, text: str) -> bool:
        return bool(VAGUE_PATTERN_RE.search(text))

    def test_dont_have_textbook(self):
        assert self._match("I don't have my textbook")

    def test_dont_have_book(self):
        assert self._match("I don't have my book")

    def test_book_is_missing(self):
        assert self._match("my book is missing")

    def test_it_doesnt_work(self):
        assert self._match("It doesn't work")

    def test_not_working(self):
        assert self._match("It's not working")

    def test_i_need_help_exact(self):
        assert self._match("I need help.")

    def test_i_cant_access_materials(self):
        assert self._match("I can't access my materials")

    def test_i_cant_find_anything(self):
        assert self._match("I can't find anything")

    # ── Book access regression (fix/intake-vague-book-access) ─────────────────
    def test_cant_access_my_book(self):
        assert self._match("I can't access my book")

    def test_cant_access_to_my_book(self):
        assert self._match("I can't access to my book")

    def test_cant_open_my_textbook(self):
        assert self._match("I can't open my textbook")

    def test_dont_see_course_materials(self):
        assert self._match("I don't see my course materials")

    def test_ebook_is_missing(self):
        assert self._match("My ebook is missing")

    def test_book_is_not_working(self):
        assert self._match("My book is not working")

    def test_cant_get_into_my_textbook(self):
        assert self._match("I can't get into my textbook")

    def test_it_says_dont_have_access(self):
        assert self._match("It says I don't have access")

    def test_platform_mention_not_vague(self):
        # "I can't access Cengage" should NOT match vague patterns
        # (no platform keyword in patterns — this tests that specific platform sentences
        # don't accidentally match generic vague patterns)
        assert not self._match("I can't access Cengage MindTap")

    def test_specific_refund_question_not_vague(self):
        assert not self._match("What is the textbook refund policy?")

    def test_greeting_not_vague(self):
        assert not self._match("Hello, can you help me?")


# ── SlotExtractor ─────────────────────────────────────────────────────────────

class TestExtractPlatform:
    def test_cengage_detected(self):
        assert extract_platform("I can't access Cengage") is not None

    def test_vitalsource_detected(self):
        result = extract_platform("my VitalSource book won't load")
        assert result is not None

    def test_no_platform_returns_none(self):
        assert extract_platform("my book is missing") is None

    def test_ambiguous_two_platforms_returns_none(self):
        # Two platforms mentioned — should return None (ambiguous)
        result = extract_platform("I have Cengage and VitalSource")
        assert result is None

    def test_case_insensitive(self):
        result = extract_platform("CENGAGE MINDTAP won't load")
        assert result is not None


class TestExtractIssueType:
    def test_access_signal(self):
        assert extract_issue_type("I can't access the book") == "access"

    def test_missing_signal(self):
        assert extract_issue_type("my textbook is missing") == "missing"

    def test_account_signal(self):
        assert extract_issue_type("I forgot my password") == "account"

    def test_no_signal_returns_none(self):
        assert extract_issue_type("general question") is None

    def test_account_priority_over_access(self):
        assert extract_issue_type("I can't login to my account") == "account"

    # VitalSource zero-content patterns (Bugfix: "0 Courses, 0 Materials" must not enter intake)
    def test_zero_courses_zero_materials_is_missing(self):
        assert extract_issue_type("I see '0 Courses, 0 Materials' on VitalSource") == "missing"

    def test_zero_courses_zero_materials_lowercase_is_missing(self):
        assert extract_issue_type("VitalSource says 0 courses 0 materials") == "missing"

    def test_no_content_available_is_missing(self):
        assert extract_issue_type("VitalSource says no content available") == "missing"

    def test_no_materials_showing_is_missing(self):
        assert extract_issue_type("My VitalSource bookshelf has no materials") == "missing"

    def test_nothing_showing_is_missing(self):
        assert extract_issue_type("nothing showing in VitalSource") == "missing"

    def test_cant_see_textbook_is_missing(self):
        assert extract_issue_type("I can't see my textbook on VitalSource") == "missing"

    def test_no_courses_is_missing(self):
        assert extract_issue_type("no courses, no materials on VitalSource") == "missing"


class TestExtractCourseCode:
    def test_standard_code(self):
        assert extract_course_code("for CS101 class") == "CS101"

    def test_code_with_space(self):
        result = extract_course_code("ENGL 1301 textbook")
        assert result == "ENGL1301"

    def test_no_code_returns_none(self):
        assert extract_course_code("I need help with my book") is None

    def test_code_case_insensitive(self):
        result = extract_course_code("class cs101 is missing book")
        assert result == "CS101"

    def test_course_code_is_optional_for_phase_3_completion(self):
        profile = IntakeProfile(platform="CENGAGE", issue_type="access", course_code=None)
        assert intake_is_complete(profile)


class TestExtractMaterialType:
    def test_textbook(self):
        assert extract_material_type("my textbook is missing") == "textbook"

    def test_ebook(self):
        assert extract_material_type("the ebook won't open") == "textbook"

    def test_workbook(self):
        assert extract_material_type("the workbook is not there") == "workbook"

    def test_lab(self):
        assert extract_material_type("my lab manual is gone") == "lab"

    def test_no_material_returns_none(self):
        assert extract_material_type("I have a question") is None


# ── Flow functions ────────────────────────────────────────────────────────────

class TestIsVagueMessage:
    def test_true_for_vague(self):
        assert is_vague_message("I don't have my textbook")

    def test_false_for_specific(self):
        assert not is_vague_message("How do I access Cengage MindTap?")

    def test_false_for_greeting(self):
        assert not is_vague_message("Hi there!")


class TestShouldEnterIntake:
    def _empty_session(self):
        return {}

    def test_enters_for_vague_message_no_platform(self):
        assert should_enter_intake("I don't have my textbook", self._empty_session())

    def test_skips_when_platform_and_issue_are_both_detected(self):
        # VitalSource alias in message — no intake needed
        assert not should_enter_intake("my VitalSource book is missing", self._empty_session())

    @pytest.mark.parametrize(
        "message",
        [
            "VitalSource issue.",
            "Cengage is not working.",
            "Pearson problem.",
            "My McGraw Hill is confusing.",
            "I have a Cengage question.",
            "McGraw Hill does not show anything.",
        ],
    )
    def test_enters_for_platform_present_issue_missing_vague_messages(self, message):
        assert should_enter_intake(message, self._empty_session())

    @pytest.mark.parametrize(
        "message",
        [
            "How do I access my Cengage MindTap book?",
            "I cannot open my McGraw Hill Connect assignment.",
            "How do I create a VitalSource Bookshelf account?",
        ],
    )
    def test_skips_for_specific_platform_questions(self, message):
        assert not should_enter_intake(message, self._empty_session())

    # ── Book access regression (fix/intake-vague-book-access) ─────────────────
    @pytest.mark.parametrize(
        "message",
        [
            "I can't access my book",
            "I can't access to my book",
            "I can't open my textbook",
            "I don't see my course materials",
            "My ebook is missing",
            "My book is not working",
            "I can't get into my textbook",
            "It says I don't have access",
        ],
    )
    def test_enters_for_vague_book_access_prompts(self, message):
        assert should_enter_intake(message, self._empty_session())

    @pytest.mark.parametrize(
        "message",
        [
            "I can't access my Cengage MindTap book",
            "McGraw Hill Connect is asking for an access code",
            "How do I create a VitalSource Bookshelf account",
            "I don't have access to my Cengage book",
        ],
    )
    def test_skips_for_platform_specific_book_access_prompts(self, message):
        assert not should_enter_intake(message, self._empty_session())

    def test_skips_when_intake_profile_active(self):
        session = {"intake_profile": {"platform": None, "issue_type": None, "turns_spent": 1, "original_message": "x", "material_type": None, "course_code": None}}
        assert not should_enter_intake("I don't have my book", session)

    def test_skips_when_awaiting_platform_type(self):
        session = {"awaiting_platform_type": True}
        assert not should_enter_intake("I don't have my book", session)

    def test_skips_when_awaiting_publisher_list(self):
        session = {"awaiting_publisher_list_response": True}
        assert not should_enter_intake("I don't have my book", session)

    def test_skips_for_non_vague_message(self):
        assert not should_enter_intake("What is the refund policy?", self._empty_session())


class TestUpdateProfile:
    def test_fills_platform(self):
        p = IntakeProfile(original_message="help")
        p = update_profile(p, "I use Cengage MindTap")
        assert p.platform is not None

    def test_fills_issue_type(self):
        p = IntakeProfile(original_message="help", platform="CENGAGE")
        p = update_profile(p, "I can't access it")
        assert p.issue_type == "access"

    def test_increments_turns(self):
        p = IntakeProfile(original_message="help", turns_spent=1)
        p = update_profile(p, "cengage")
        assert p.turns_spent == 2

    def test_does_not_overwrite_existing_platform(self):
        p = IntakeProfile(original_message="help", platform="CENGAGE")
        p = update_profile(p, "I use VitalSource now")
        assert p.platform == "CENGAGE"


class TestNextQuestion:
    def test_asks_platform_first(self):
        p = IntakeProfile()
        q = intake_next_question(p)
        assert q == NEXT_QUESTION["platform"]

    def test_asks_issue_after_platform(self):
        p = IntakeProfile(platform="CENGAGE")
        q = intake_next_question(p)
        assert q == NEXT_QUESTION["issue_type"]

    def test_none_when_complete(self):
        p = IntakeProfile(platform="CENGAGE", issue_type="access")
        assert intake_next_question(p) is None

    def test_none_when_expired(self):
        p = IntakeProfile(turns_spent=3)
        assert intake_next_question(p) is None


class TestIntakeFallbackMessage:
    def test_returns_string(self):
        assert isinstance(intake_fallback_message(), str)
        assert len(intake_fallback_message()) > 0

    def test_matches_constant(self):
        assert intake_fallback_message() == INTAKE_FALLBACK_MESSAGE


# ── Multi-turn lifecycle tests ────────────────────────────────────────────────

class TestMultiTurnLifecycle:
    """
    Simulate the call sequence that app/main.py would perform.
    """

    def _new_session(self) -> dict:
        return {}

    def _display_names(self) -> dict:
        return {"CENGAGE": "Cengage MindTap", "VITALSOURCE": "VitalSource"}

    def test_full_two_turn_completion(self):
        """Vague → platform answer → issue answer → complete."""
        session = self._new_session()

        # Turn 1: vague message enters intake
        msg1 = "I don't have my textbook"
        assert should_enter_intake(msg1, session)
        profile = IntakeProfile(original_message=msg1)
        profile = update_profile(profile, msg1)
        assert not intake_is_complete(profile)
        q1 = intake_next_question(profile)
        assert "platform" in q1.lower() or "publisher" in q1.lower()
        session["intake_profile"] = profile.to_dict()

        # Turn 2: student says "Cengage" — fills platform slot
        msg2 = "It's Cengage MindTap"
        profile = IntakeProfile.from_dict(session["intake_profile"])
        profile = update_profile(profile, msg2)
        assert profile.platform is not None
        assert not intake_is_complete(profile)  # still need issue_type
        q2 = intake_next_question(profile)
        assert "issue" in q2.lower() or "problem" in q2.lower() or "trouble" in q2.lower()
        session["intake_profile"] = profile.to_dict()

        # Turn 3: student says "I can't access it" — fills issue_type
        msg3 = "I can't access it"
        profile = IntakeProfile.from_dict(session["intake_profile"])
        profile = update_profile(profile, msg3)
        assert intake_is_complete(profile)
        session["intake_profile"] = None

        enriched = profile.build_enriched_query(self._display_names())
        assert "Cengage MindTap" in enriched
        assert "access" in enriched

    def test_single_turn_completion(self):
        """Message already contains platform + issue signals → complete after first update."""
        session = self._new_session()
        # Not truly vague — contains both platform and issue. should_enter_intake would
        # return False for this (platform detected). But we test update_profile directly.
        msg = "I can't access my Cengage textbook"
        profile = IntakeProfile(original_message=msg)
        profile = update_profile(profile, msg)
        assert intake_is_complete(profile)

    def test_expiry_after_max_turns(self):
        """After _MAX_INTAKE_TURNS turns with no completion, profile expires."""
        session = self._new_session()
        msg1 = "I don't have my textbook"
        profile = IntakeProfile(original_message=msg1)

        for _ in range(3):
            profile = update_profile(profile, "I don't know")

        assert profile.is_expired()
        assert not intake_is_complete(profile)
        assert intake_next_question(profile) is None

    def test_specific_platform_issue_bypasses_intake(self):
        """Specific platform questions with an issue type skip intake."""
        session = self._new_session()
        msg = "I can't access VitalSource"
        assert not should_enter_intake(msg, session)

    def test_safety_not_bypassed_by_intake_flag(self):
        """
        Intake session flag does NOT change should_enter_intake for same session —
        the mid-intake path is handled by the non-None intake_profile check.
        """
        session = {"intake_profile": {"platform": None, "issue_type": None, "turns_spent": 1, "original_message": "x", "material_type": None, "course_code": None}}
        # A vague follow-up should NOT re-enter intake (mid-intake is handled separately)
        assert not should_enter_intake("I still don't have my book", session)


# ── Phase 8: LLM intake planner ───────────────────────────────────────────────

class TestIntakePlannerDecisionModel:
    def test_allow_rag_action(self):
        d = IntakePlannerDecision(
            action="ALLOW_RAG", intent="specific", confidence=0.9,
            known_slots={"platform": "CENGAGE"}, missing_slots=[],
        )
        assert d.action == "ALLOW_RAG"

    def test_ask_clarification_action(self):
        d = IntakePlannerDecision(
            action="ASK_CLARIFICATION", intent="vague", confidence=0.8,
            known_slots={}, missing_slots=["platform"],
            next_question_key="ask_platform_for_book_access",
        )
        assert d.action == "ASK_CLARIFICATION"
        assert d.next_question_key == "ask_platform_for_book_access"

    def test_optional_fields_default_none(self):
        d = IntakePlannerDecision(
            action="ALLOW_RAG", intent="x", confidence=0.5,
            known_slots={}, missing_slots=[],
        )
        assert d.next_question_key is None
        assert d.enriched_query is None

    def test_invalid_action_raises(self):
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            IntakePlannerDecision(
                action="INVALID", intent="x", confidence=0.5,
                known_slots={}, missing_slots=[],
            )

    def test_enriched_query_stored(self):
        d = IntakePlannerDecision(
            action="ALLOW_RAG", intent="specific", confidence=0.9,
            known_slots={}, missing_slots=[],
            enriched_query="Cengage MindTap access issue",
        )
        assert d.enriched_query == "Cengage MindTap access issue"


class TestQuestionTemplates:
    _EXPECTED_KEYS = {
        "ask_platform_for_book_access",
        "ask_issue_for_platform",
        "ask_course_code",
        "ask_error_message",
        "ask_material_type",
        "ask_blackboard_or_publisher_location",
    }

    def test_all_required_keys_present(self):
        assert self._EXPECTED_KEYS.issubset(set(QUESTION_TEMPLATES.keys()))

    def test_all_values_non_empty_strings(self):
        for key, value in QUESTION_TEMPLATES.items():
            assert isinstance(value, str) and len(value) > 0, f"Empty string for key {key!r}"

    def test_fallback_question_defined(self):
        assert isinstance(FALLBACK_QUESTION, str) and len(FALLBACK_QUESTION) > 0

    def test_get_question_for_known_key(self):
        decision = IntakePlannerDecision(
            action="ASK_CLARIFICATION", intent="x", confidence=0.9,
            known_slots={}, missing_slots=[],
            next_question_key="ask_platform_for_book_access",
        )
        q = get_question_for_decision(decision)
        assert q == QUESTION_TEMPLATES["ask_platform_for_book_access"]

    def test_get_question_for_none_key_returns_fallback(self):
        decision = IntakePlannerDecision(
            action="ASK_CLARIFICATION", intent="x", confidence=0.9,
            known_slots={}, missing_slots=[],
            next_question_key=None,
        )
        assert get_question_for_decision(decision) == FALLBACK_QUESTION

    def test_platform_question_mentions_examples(self):
        q = QUESTION_TEMPLATES["ask_platform_for_book_access"]
        assert "VitalSource" in q or "Cengage" in q


class TestShouldRunPlanner:
    def test_book_triggers_planner(self):
        assert should_run_planner("My book is locked")

    def test_textbook_triggers_planner(self):
        assert should_run_planner("I can't find the textbook")

    def test_ebook_triggers_planner(self):
        assert should_run_planner("My ebook is not loading")

    def test_access_triggers_planner(self):
        assert should_run_planner("I lost access somehow")

    def test_platform_name_triggers_planner(self):
        assert should_run_planner("Something is wrong with cengage")

    def test_material_triggers_planner(self):
        assert should_run_planner("My course materials are gone")

    def test_store_hours_skips_planner(self):
        assert not should_run_planner("What are the store hours?")

    def test_greeting_skips_planner(self):
        assert not should_run_planner("Hi there")

    def test_refund_only_skips_planner(self):
        assert not should_run_planner("I want a refund")

    @pytest.mark.parametrize(
        "message",
        [
            "How do I opt out of Immediate Access?",
            "How do I opt out in Canvas?",
            "Can I opt out of Immediate Access?",
            "Where do I opt out?",
            "What is Immediate Access?",
            "What is the textbook refund policy?",
            "How do I return a textbook?",
            "Can I get a refund?",
            "Where do I buy my textbooks?",
        ],
    )
    def test_policy_faq_questions_skip_planner(self, message):
        assert not should_run_planner(message)

    def test_platform_and_issue_present_skips_planner(self):
        # Both slots deterministically present — planner adds no value
        assert not should_run_planner("I can't access my Cengage MindTap book")

    def test_platform_only_still_runs_planner(self):
        # Platform present but no issue type — clarification still needed
        assert should_run_planner("Something is wrong with Cengage")

    def test_known_slots_both_present_skips_planner(self):
        # Both slots known from session — planner adds no value
        assert not should_run_planner(
            "I can't access the textbook",
            known_slots={"platform": "CENGAGE", "issue_type": "access"},
        )

    def test_known_slots_platform_only_still_runs_planner(self):
        # Only platform known — issue_type still missing
        assert should_run_planner(
            "I can't access the textbook",
            known_slots={"platform": "CENGAGE"},
        )

    def test_known_slots_empty_dict_still_runs_planner(self):
        assert should_run_planner("My book is locked", known_slots={})

    def test_known_slots_none_still_runs_planner(self):
        assert should_run_planner("My book is locked", known_slots=None)

    def test_zero_courses_zero_materials_vitalsource_skips_planner(self):
        # Both platform (VitalSource) and issue (missing) are extractable — planner adds no value
        assert not should_run_planner("I see 0 Courses 0 Materials on VitalSource")

    def test_no_content_available_vitalsource_skips_planner(self):
        assert not should_run_planner("VitalSource says no content available")

    def test_cant_see_textbook_vitalsource_skips_planner(self):
        assert not should_run_planner("I can't see my textbook on VitalSource")


# ── is_unknown_answer ─────────────────────────────────────────────────────────

class TestIsUnknownAnswer:
    def test_i_dont_know(self):
        assert is_unknown_answer("I don't know")

    def test_i_dont_know_contraction(self):
        assert is_unknown_answer("I dont know")

    def test_i_do_not_know(self):
        assert is_unknown_answer("I do not know")

    def test_not_sure(self):
        assert is_unknown_answer("not sure")

    def test_im_not_sure(self):
        assert is_unknown_answer("I'm not sure")

    def test_no_idea(self):
        assert is_unknown_answer("no idea")

    def test_i_have_no_idea(self):
        assert is_unknown_answer("I have no idea")

    def test_unsure(self):
        assert is_unknown_answer("unsure")

    def test_not_sure_which(self):
        assert is_unknown_answer("not sure which platform")

    def test_no_clue(self):
        assert is_unknown_answer("no clue")

    def test_platform_name_is_not_unknown(self):
        assert not is_unknown_answer("Cengage MindTap")

    def test_normal_message_is_not_unknown(self):
        assert not is_unknown_answer("My book is locked")

    def test_partial_match_still_detected(self):
        assert is_unknown_answer("I really don't know which publisher")


# ── IntakeProfile new fields ──────────────────────────────────────────────────

class TestIntakeProfileUnknownSlots:
    def test_last_requested_slot_default_none(self):
        p = IntakeProfile()
        assert p.last_requested_slot is None

    def test_attempted_slots_default_empty(self):
        p = IntakeProfile()
        assert p.attempted_slots == []

    def test_last_requested_slot_roundtrip(self):
        p = IntakeProfile(original_message="help", last_requested_slot="platform")
        p2 = IntakeProfile.from_dict(p.to_dict())
        assert p2.last_requested_slot == "platform"

    def test_attempted_slots_roundtrip(self):
        p = IntakeProfile(original_message="help")
        p.attempted_slots = ["platform", "course_or_material"]
        p2 = IntakeProfile.from_dict(p.to_dict())
        assert p2.attempted_slots == ["platform", "course_or_material"]

    def test_from_dict_missing_new_fields_uses_defaults(self):
        d = {
            "platform": None, "issue_type": None, "material_type": None,
            "course_code": None, "turns_spent": 1, "original_message": "x",
        }
        p = IntakeProfile.from_dict(d)
        assert p.last_requested_slot is None
        assert p.attempted_slots == []

    def test_to_dict_includes_new_fields(self):
        p = IntakeProfile(original_message="x", last_requested_slot="issue_type")
        p.attempted_slots = ["platform"]
        d = p.to_dict()
        assert d["last_requested_slot"] == "issue_type"
        assert d["attempted_slots"] == ["platform"]


# ── question_templates new additions ─────────────────────────────────────────

class TestQuestionTemplatesUnknownPlatform:
    def test_new_template_present(self):
        assert "ask_course_or_material_when_platform_unknown" in QUESTION_TEMPLATES

    def test_template_contains_email_address(self):
        q = QUESTION_TEMPLATES["ask_course_or_material_when_platform_unknown"]
        assert "ImmediateAccess@calbaptist.edu" in q

    def test_template_does_not_ask_for_course_code_or_instructor(self):
        q = QUESTION_TEMPLATES["ask_course_or_material_when_platform_unknown"].lower()
        assert "course code" not in q
        assert "instructor" not in q
        assert "student id" not in q

    def test_question_key_to_slot_has_new_key(self):
        assert "ask_course_or_material_when_platform_unknown" in QUESTION_KEY_TO_SLOT

    def test_platform_key_maps_to_platform_slot(self):
        assert QUESTION_KEY_TO_SLOT["ask_platform_for_book_access"] == "platform"

    def test_new_key_maps_to_course_or_material(self):
        assert QUESTION_KEY_TO_SLOT["ask_course_or_material_when_platform_unknown"] == "course_or_material"


# ── Phase 8: planner model config ─────────────────────────────────────────────

class TestPlannerModelConfig:
    """run_intake_planner must use INTAKE_PLANNER_* vars and correct payload options."""

    @staticmethod
    def _make_success_response(action: str = "ALLOW_RAG") -> MagicMock:
        content = json.dumps({
            "action": action,
            "intent": "test",
            "confidence": 0.9,
            "known_slots": {},
            "missing_slots": [],
            "next_question_key": None,
            "enriched_query": None,
        })
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"ok"
        resp.json.return_value = {"message": {"content": content}}
        return resp

    @staticmethod
    def _mock_client(post_fn):
        """Return a context-manager-compatible mock client with the given post function."""
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = post_fn
        return client

    def test_planner_uses_intake_planner_model(self):
        """Payload 'model' must be INTAKE_PLANNER_MODEL, not PRIMARY_LLM_MODEL."""
        captured: list[dict] = []

        async def mock_post(url, json=None, **kw):
            captured.append(json or {})
            return self._make_success_response()

        with patch("app.intake.llm_planner.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = self._mock_client(mock_post)
            asyncio.run(run_intake_planner("my book is locked"))

        assert captured, "post() was never called"
        assert captured[0].get("model") == INTAKE_PLANNER_MODEL

    def test_planner_payload_includes_format_json(self):
        """Payload must include 'format': 'json' to request JSON-mode output."""
        captured: list[dict] = []

        async def mock_post(url, json=None, **kw):
            captured.append(json or {})
            return self._make_success_response()

        with patch("app.intake.llm_planner.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = self._mock_client(mock_post)
            asyncio.run(run_intake_planner("my book is locked"))

        assert captured[0].get("format") == "json"

    def test_planner_payload_num_predict_matches_max_tokens(self):
        """options.num_predict must equal _PLANNER_MAX_TOKENS."""
        captured: list[dict] = []

        async def mock_post(url, json=None, **kw):
            captured.append(json or {})
            return self._make_success_response()

        with patch("app.intake.llm_planner.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = self._mock_client(mock_post)
            asyncio.run(run_intake_planner("my book is locked"))

        assert captured[0].get("options", {}).get("num_predict") == _PLANNER_MAX_TOKENS

    def test_planner_fallback_model_used_on_primary_http_error(self):
        """When primary model returns HTTP 500, the fallback model is tried next."""
        call_count = 0
        captured_models: list[str] = []

        async def mock_post(url, json=None, **kw):
            nonlocal call_count
            call_count += 1
            captured_models.append((json or {}).get("model", ""))
            if call_count == 1:
                resp = MagicMock()
                resp.status_code = 500
                resp.content = b"server error"
                return resp
            return self._make_success_response()

        with patch("app.intake.llm_planner.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = self._mock_client(mock_post)
            asyncio.run(run_intake_planner("my book is locked"))

        assert INTAKE_PLANNER_FALLBACK_MODEL in captured_models

    def test_planner_timeout_fails_safe_to_ask_clarification(self):
        """TimeoutException on all models must return ASK_CLARIFICATION, not raise."""
        import httpx as _httpx

        async def mock_post(url, json=None, **kw):
            raise _httpx.TimeoutException("timed out", request=None)

        with patch("app.intake.llm_planner.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = self._mock_client(mock_post)
            result = asyncio.run(run_intake_planner("my book is locked"))

        assert result.action == "ASK_CLARIFICATION"


# -- Book-location intent / issue_type extraction ----------------------------

class TestBookLocationIssueTypeExtraction:
    """'Where can I see/find/access my book?' patterns must extract issue_type='access'."""

    @pytest.mark.parametrize("message", [
        "Where can I see my book?",
        "Where do I find my digital textbook?",
        "Where can I access my textbook?",
        "Where is my ebook?",
        "Where can I find my book?",
        "Where can I see my textbook?",
        "Where do I get my textbook?",
    ])
    def test_book_location_extracts_access(self, message: str) -> None:
        assert extract_issue_type(message) == "access", (
            f"Expected issue_type='access' for {message!r}"
        )

    def test_book_location_with_cengage_extracts_platform(self) -> None:
        """'Where can I see my Cengage book?' extracts platform=CENGAGE even without issue signal."""
        assert extract_platform("Where can I see my Cengage book?") == "CENGAGE"
        # issue_type=None for this message: 'cengage' sits between 'my' and 'book'
        # so the pattern 'where can i see my book' doesn't match. The planner's
        # intent mapping (book_location -> access) covers this case.

    def test_where_can_i_access_my_textbook_extracts_issue(self) -> None:
        """'Where can I access my textbook?' extracts issue_type=access (no platform word between)."""
        assert extract_issue_type("Where can I access my textbook?") == "access"

    def test_plain_where_without_book_does_not_match(self) -> None:
        """Bare 'where can i see my' without a book/material keyword must not false-positive."""
        assert extract_issue_type("where can i see my schedule") is None

    def test_vitalsource_issue_still_none(self) -> None:
        """'VitalSource issue' has no issue_type signal (no access/missing/account word)."""
        assert extract_issue_type("VitalSource issue") is None

    @pytest.mark.parametrize("alias", ["cengage", "Cengage Mindtap", "MindTap", "cnow"])
    def test_cengage_aliases_normalize_to_cengage(self, alias: str) -> None:
        """All Cengage aliases must resolve to the CENGAGE platform key."""
        assert extract_platform(alias) == "CENGAGE", (
            f"Expected CENGAGE for alias {alias!r}"
        )


class TestPlannerBookLocationIntentMapping:
    """
    When the planner returns intent='book_location' and asks for a slot
    already extracted, main.py must pre-set issue_type and redirect to the
    next missing slot.
    """

    def _make_book_location_decision(self, next_q: str = "ask_material_type") -> IntakePlannerDecision:
        return IntakePlannerDecision(
            action="ASK_CLARIFICATION",
            intent="book_location",
            confidence=0.70,
            known_slots={},
            missing_slots=["platform"],
            next_question_key=next_q,
            enriched_query=None,
        )

    def test_book_location_profile_has_access_and_textbook(self) -> None:
        """
        update_profile on 'Where can I see my book?' should produce
        issue_type='access' and material_type='textbook' from slot extraction.
        These slots are available before the planner-intent mapping fires.
        """
        profile = update_profile(
            IntakeProfile(original_message="Where can I see my book?"),
            "Where can I see my book?",
        )
        assert profile.issue_type == "access"
        assert profile.material_type == "textbook"
        assert profile.platform is None

    def test_intake_completes_after_platform_supplied(self) -> None:
        """
        After planner pre-sets issue_type='access', intake should complete
        as soon as platform is supplied — without needing an issue_type turn.
        """
        profile = update_profile(
            IntakeProfile(original_message="Where can I see my book?"),
            "Where can I see my book?",
        )
        # Simulate planner intent mapping: issue_type pre-set to 'access'
        # (either from slot extraction above or from intent mapping in main.py)
        assert profile.issue_type == "access"
        # Now the user supplies the platform
        profile = update_profile(profile, "Cengage MindTap")
        assert profile.platform == "CENGAGE"
        assert intake_is_complete(profile) is True

    def test_three_turn_flow_also_completes(self) -> None:
        """
        Original 3-turn flow: issue_type already set from extraction, so
        after material + platform turns the profile is complete.
        """
        profile = update_profile(
            IntakeProfile(original_message="Where can I see my book?"),
            "Where can I see my book?",
        )
        assert profile.issue_type == "access"
        # Turn 2: material_type answer (no new info since already extracted)
        profile = update_profile(profile, "digital textbook")
        # Turn 3: platform
        profile = update_profile(profile, "Cengage MindTap")
        assert profile.platform == "CENGAGE"
        assert intake_is_complete(profile) is True
        assert profile.turns_spent == 3
