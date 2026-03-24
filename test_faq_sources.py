import sys
sys.path.insert(0, '.')
from app.rag.retriever import get_retriever
from app.main import (
    is_browser_cache_issue,
    is_ia_overview_query,
    is_merchandise_query,
    is_merchandise_return_query,
    is_technology_return_query,
    is_textbook_return_query,
    build_browser_cache_faq_query,
)

r = get_retriever()

# Check specific source IDs from the test results
source_ids = [
    'FAQ_SOURCE_7',
    'FAQ_SOURCE_11',
    'FAQ_SOURCE_4',
    'FAQ_SOURCE_2',
    'FAQ_SOURCE_12',
    'FAQ_SOURCE_9',
    'FAQ_SOURCE_34',
    'FAQ_SOURCE_13',
    'FAQ_SOURCE_24',
]

queries = [
    ('How do I place an order', 'faqs'),
    ('What is the shipping policy', 'faqs'),
    ('In store pickup policy', 'faqs'),
    ('What are digital codes', 'faqs'),
    ('Textbook purchasing terms', 'faqs'),
    ('How do I return merchandise', 'faqs'),
    ('Return policy for technology', 'faqs'),
    ('Textbook rental agreement', 'faqs'),
    ('How do I return a textbook', 'faqs'),
]


def build_faq_query(message: str) -> str:
    lowered = (message or "").lower()

    if is_textbook_return_query(message):
        if any(
            signal in lowered
            for signal in [
                "refund policy for immediate access",
                "refund policy immediate access",
                "immediate access refund",
                "immediate access charge",
                "charged for immediate access",
            ]
        ):
            return "Immediate Access refund policy opt out deadline charge final sale student account"
        return "how to return textbook shipping in person CBU Campus Store deadlines refund policy Immediate Access"

    if is_merchandise_return_query(message):
        return "campus store refund merchandise apparel clothing trade books altered laundered tags receipt required final sale 60 days"

    if is_technology_return_query(message):
        return "return technology Apple laptop computer tablet 5 days restocking fee defective original packaging"

    if is_merchandise_query(message):
        return "CBU Campus Store merchandise apparel clothing mugs gifts supplies"

    if is_ia_overview_query(message):
        return "Immediate Access program overview day-one digital course materials student account CBU definition"

    if is_browser_cache_issue(message):
        return build_browser_cache_faq_query(message)

    return message

print("Query -> Source ID -> Source File")
print("-" * 80)
for q, col in queries:
    result = r.retrieve(build_faq_query(q), collection=col)
    source_id = result.get('source_id', 'N/A')
    context = result.get('context', '')
    # Extract source_file from META header if present
    source_file = 'unknown'
    if '[META:' in context:
        import json
        try:
            meta_str = context.split('[META:')[1].split(']')[0]
            meta = json.loads(meta_str)
            source_file = meta.get('source_file', 'unknown')
        except Exception:
            pass
    print(f"{q:<42} -> {source_id:<20} -> {source_file}")
