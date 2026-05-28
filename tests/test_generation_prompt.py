from app.llm import llama_client
from app.llm.llama_client import build_grounded_prompt, build_system_prompt


def test_system_prompt_requires_context_only_answers():
    prompt = build_system_prompt(
        context="QUESTION:\nWhat is Immediate Access?\n\nANSWER:\nImmediate Access is documented here.",
    )
    lowered = prompt.lower()

    assert "use only the retrieved campus store documentation" in lowered
    assert "do not add platform steps" in lowered
    assert "emails, phone numbers, urls" in lowered
    assert "deadlines" in lowered
    assert "fees" in lowered
    assert "i do not have enough information in the campus store documentation to answer that fully" in lowered


def test_grounded_prompt_handles_multiple_workflows_rule():
    prompt = build_grounded_prompt(
        "I can't access my McGraw Hill Connect textbook",
        "OPTION 1 - Learning Activities tab\nOPTION 2 - Tools tab",
    )
    lowered = prompt.lower()

    assert "multiple retrieved sources contain different workflows" in lowered
    assert "may depend on course or platform setup" in lowered
    assert "present only the workflows actually present in the context" in lowered
    assert "do not choose one workflow as universally correct" in lowered


def test_grounded_prompt_prevents_unsupported_contact_policy_details():
    prompt = build_grounded_prompt(
        "What is the refund policy?",
        "The context mentions only a 14-day opt-out period.",
    )
    lowered = prompt.lower()

    assert "do not add" in lowered
    assert "refund rules" in lowered
    assert "return rules" in lowered
    assert "phone numbers" in lowered
    assert "urls" in lowered
    assert "unless they appear in the context" in lowered


def test_grounded_prompt_contains_insufficient_documentation_fallback():
    prompt = build_grounded_prompt("Where is the office?", "No location is listed.")

    assert (
        'say: "I do not have enough information in the Campus Store documentation to answer that fully."'
        in prompt
    )


def test_rag_generation_options_are_low_temperature(monkeypatch):
    captured_payloads = []

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"message": {"content": "ok"}}

    def fake_post(url, json, timeout):
        captured_payloads.append(json)
        return DummyResponse()

    monkeypatch.setattr(llama_client.requests, "post", fake_post)

    client = llama_client.LlamaClient()
    assert client.chat("What is Immediate Access?", context="ANSWER:\nDocumented answer.") == "ok"

    assert captured_payloads
    assert captured_payloads[0]["options"]["temperature"] <= 0.1
    assert captured_payloads[0]["options"]["num_predict"] == llama_client.RAG_NUM_PREDICT
