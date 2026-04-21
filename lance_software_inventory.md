# Lance - Software & Frameworks Inventory

## Backend

| Software | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Primary backend language |
| FastAPI | Latest | Web framework — API routing, endpoints, request handling |
| uvicorn | Latest | ASGI server — runs the FastAPI application |
| Pydantic | v2 | Request/response schema validation |
| httpx | Latest | Async HTTP client — used for Ollama streaming requests |
| python-dotenv | Latest | Loads environment variables from `.env` file |

## AI / Machine Learning

| Software | Version | Purpose |
|---|---|---|
| Ollama | Latest | Local LLM runtime — serves the language model |
| Gemma 4 E2B (`gemma4:e2b`) | April 2025 | Language model — Google DeepMind, 2.3B effective parameters, reasoning-capable |
| FAISS (`faiss-cpu`) | Latest | Vector similarity search — powers the retrieval system |
| Sentence Transformers | Latest | Embedding model framework |
| `all-MiniLM-L6-v2` | — | Embedding model — converts text to 384-dimension vectors for FAISS |

## Firebase (Google Cloud)

| Service | Purpose |
|---|---|
| Firebase Hosting | Hosts the React frontend — public-facing chat UI |
| Firebase Storage | Stores PDF guide files |
| Firestore | NoSQL database — stores PDF metadata and content-to-PDF mappings |
| Firebase Admin SDK (`firebase-admin`) | Python SDK — backend access to Firestore and Storage |
| Firebase CLI | Deployment tool — builds and deploys frontend to Firebase Hosting |

## Frontend

| Software | Version | Purpose |
|---|---|---|
| React | 18+ | UI framework — chat interface |
| TypeScript | 5+ | Typed JavaScript — frontend language |
| Vite | Latest | Frontend build tool and dev server |
| Tailwind CSS | Latest | Utility-first CSS framework — styling |
| shadcn/ui | Latest | UI component library — accordion, cards, buttons |

## Networking

| Software | Purpose |
|---|---|
| ngrok (needs to be replaced) | Interim network tunnel - exposes local backend to the internet over HTTPS |

## Development & Testing

| Software | Purpose |
|---|---|
| pytest | Python test runner — 27 test cases |
| conda (Miniconda) | Python environment manager — isolates project dependencies |
| Node.js (18+) | JavaScript runtime — required for frontend build tooling and Firebase CLI |
| npm | Node package manager — frontend dependency management |
| Git | Version control |

## Operating System

| Software | Details |
|---|---|
| Windows 11 | Current deployment machine OS |

