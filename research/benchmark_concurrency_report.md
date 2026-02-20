# Chatbot Concurrent-User Benchmark Report (2026-02-20T15:19:47)

## Setup
- Base URL: `http://127.0.0.1:8000`
- Concurrency levels: `5, 6, 7, 8, 9, 10` users
- Rounds per level: `3`
- Questions tested: `5` common RAG queries

## Summary Table

| Users | Success % | Throughput (req/s) | Client p50 (ms) | Client p95 (ms) | Server p50 (ms) | Server p95 (ms) | Retrieval avg (ms) | LLM avg (ms) | GPU avg % | GPU peak % | GPU Mem avg (MB) | Quality avg | Quality pass % | RAG hit % |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100.00 | 0.304 | 11538.58 | 16445.96 | 11532.34 | 16437.74 | 37.49 | 10660.11 | 73.33 | 100.00 | 4916.00 | 0.960 | 100.00 | 100.00 |
| 6 | 100.00 | 0.311 | 13054.69 | 19360.26 | 13034.10 | 19331.83 | 45.16 | 12756.74 | 75.76 | 100.00 | 4914.15 | 0.956 | 100.00 | 100.00 |
| 7 | 100.00 | 0.322 | 13902.29 | 22598.89 | 13892.61 | 22564.59 | 55.15 | 12991.20 | 78.26 | 100.00 | 4902.81 | 0.962 | 100.00 | 100.00 |
| 8 | 100.00 | 0.337 | 12557.34 | 23717.89 | 12515.83 | 23708.54 | 59.30 | 13194.49 | 77.59 | 100.00 | 4899.66 | 0.958 | 100.00 | 100.00 |
| 9 | 100.00 | 0.337 | 15102.13 | 26691.64 | 15092.71 | 26672.22 | 67.40 | 15616.35 | 78.94 | 100.00 | 4899.00 | 0.956 | 100.00 | 100.00 |
| 10 | 100.00 | 0.327 | 17815.94 | 30108.78 | 17792.67 | 30069.14 | 72.86 | 17516.02 | 81.72 | 100.00 | 4898.40 | 0.960 | 100.00 | 100.00 |

## Notes
- `Quality avg` is a lightweight heuristic: 60% keyword relevance + 40% RAG/source hit.
- `RAG hit` means source was not `LLM_ONLY` and confidence was >= 0.1.
- Use this as a comparative benchmark across concurrency levels.
