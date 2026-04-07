import sys
sys.path.insert(0, '.')
from app.rag.retriever import get_retriever

r = get_retriever()

queries = [
    ('How do I place an order', 'faqs'),
    ('What is the shipping policy', 'faqs'),
    ('In store pickup policy', 'faqs'),
    ('What are digital codes', 'faqs'),
    ('Textbook purchasing terms', 'faqs'),
    ('How do I return merchandise', 'faqs'),
    ('Return policy for technology', 'faqs'),
    ('How do I return something', 'faqs'),
    ('Textbook rental agreement', 'faqs'),
    ('How do I return a textbook', 'faqs'),
]

for q, col in queries:
    result = r.retrieve(q, collection=col)
    source = result.get('source_id', 'N/A')
    score = result.get('score', 0)
    print(f"{q:<42} -> {source} ({score:.3f})")