HARMFUL_REFUSAL = (
    "I can't help with instructions that could cause harm, unauthorized access, or illegal activity. "
    "If you need help with Campus Store, Immediate Access, or course material access, "
    "please ask about that directly."
)

OUT_OF_SCOPE_FALLBACK = (
    "I don't have specific information about that. "
    "Please contact ImmediateAccess@calbaptist.edu for assistance."
)

ABUSE_REFUSAL = (
    "I can help with Campus Store, Immediate Access, textbooks, and course material access questions. "
    "Please rephrase your question so I can assist you."
)

NEEDS_HUMAN_REVIEW = (
    "This may require help from Campus Store staff. "
    "Please contact ImmediateAccess@calbaptist.edu for assistance."
)

ASK_CLARIFICATION = (
    "I want to make sure I understand your question correctly. "
    "I can help with Immediate Access, textbook access, course materials, returns, and Campus Store policies. "
    "Could you describe what you need help with?"
)

TEMPLATES: dict[str, str] = {
    "harmful_refusal": HARMFUL_REFUSAL,
    "out_of_scope_fallback": OUT_OF_SCOPE_FALLBACK,
    "campus_store_scope_fallback": OUT_OF_SCOPE_FALLBACK,
    "abuse_refusal": ABUSE_REFUSAL,
    "needs_human_review": NEEDS_HUMAN_REVIEW,
    "ask_clarification": ASK_CLARIFICATION,
}


def get_template(name: str) -> str:
    return TEMPLATES.get(name, OUT_OF_SCOPE_FALLBACK)
