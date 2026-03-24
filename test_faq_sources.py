import sys
sys.path.insert(0, '.')
from app.rag.retriever import get_retriever

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

print("Query -> Source ID -> Source File")
print("-" * 80)
for q, col in queries:
    result = r.retrieve(q, collection=col)
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