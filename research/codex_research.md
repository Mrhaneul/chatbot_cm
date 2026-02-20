## Executive Recommendation (as of February 17, 2026)
For Lance’s 3–5 year sustainability goals, use:

1. Primary: University on-prem GPU box (self-hosted FastAPI + FAISS + embeddings + LLM).
2. Frontend: Keep on Firebase Hosting (already working, low-ops).
3. Secondary fallback: small cloud GPU endpoint only for disaster recovery (not normal traffic).
4. Model: Start with Qwen2.5-7B-Instruct (Apache-2.0), keep Phi-4-mini-instruct as fast fallback.

This is the best fit for your priorities: vendor independence, privacy, maintainability, and cost stability.

## A) Hosting Options (Full Stack)

### Option 1: All-cloud GPU VM (fastest to start, highest vendor risk)
- Typical monthly GPU compute (24/7, before egress/storage):
  - AWS G4ad reference prices shown on EC2 page: $0.379–$0.541/hr (~$277–$395/mo) for listed G4ad sizes (US-East example on page).
  - GCP GPU pricing page shows T4 at ~$0.35/hr and L4 at ~$0.56/hr (~$256 and $409/mo) plus VM/egress.
  - DigitalOcean RTX 4000 at $0.76/hr (~$555/mo); RTX 6000/L40S at $1.57/hr (~$1,146/mo).
  - Hetzner dedicated GPU examples: GEX44 around EUR184/mo, GEX131 around EUR889/mo.
- Pros: fastest launch, managed infra.
- Cons: ongoing cloud dependence, FERPA/data-governance complexity, cost drift.

### Option 2: Hybrid (Firebase frontend + cloud backend/LLM)
- Good interim model.
- Cost similar to Option 1 for backend GPU; frontend remains low.
- Better than ngrok immediately, but still cloud-vendor dependency.

### Option 3: On-prem primary + Firebase frontend (recommended)
- One-time hardware cost, lower long-run dependency risk.
- Best privacy posture (queries stay in university infrastructure).
- Needs basic IT support (UPS, patching, monitoring).

### Option 4: On-prem primary + cloud warm standby (best resilience)
- Adds failover if campus hardware fails.
- Slight extra monthly cost, best operational continuity.

## B) On-Prem Hardware Direction

### Practical tiers
1. Cost-efficient production: single NVIDIA workstation GPU (24–48GB VRAM class).
2. Low-ops Apple path: Mac Studio (M4 Max / M3 Ultra) for simpler maintenance and lower power.
3. Enterprise NVIDIA pro: RTX 6000 Ada class (very capable, expensive).

### Concrete references
- RTX 6000 Ada listed around $6,800 GPU-only.
- Mac Studio starts around $1,999 (M4 Max) and $3,999 (M3 Ultra).
- Apple support lists max power around 145W (M4 Max) and 270W (M3 Ultra).
- California average retail electricity: 27.04 cents/kWh (useful for ops cost planning).

### GPU vs CPU
- GPU strongly preferred for sub-5s UX at semester peaks.
- CPU-only can work for very small models but is risky for latency consistency.
- For throughput intuition: Microsoft’s Phi-3 ONNX page reports high TPS on RTX 4090 test setup for a small model; CPU-only generally won’t match that headroom.

## C) Model Comparison for RAG Use Case

### Best fit shortlist
1. Qwen2.5-7B-Instruct
   - Strong instruction following, good structured output behavior, Apache-2.0.
2. Mistral-7B-Instruct-v0.3
   - Reliable 7B option, Apache-2.0, strong ecosystem.
3. Phi-4-mini-instruct (3.8B)
   - Fast, MIT license, great fallback for latency/concurrency pressure.

### Use with caution
- Llama 3.1/3.3: strong quality, but custom community license (not Apache/MIT).
- Gemma 2: good quality, but gated terms/usage policy acceptance.
- DeepSeek-R1-distill: powerful reasoning, but often overkill for campus support FAQ flows and can be verbose/slower.

### Recommended production strategy
- Primary model: Qwen2.5-7B-Instruct (quantized for your hardware).
- Fallback model: Phi-4-mini-instruct for peak loads or degraded mode.
- Force strict RAG behavior with prompt policy: “answer only from retrieved context; otherwise say unknown.”

## D) Risk & Sustainability ("Fire-and-Forget" Design)

### Target architecture
- Firebase Hosting (UI)
- On-prem FastAPI service (RAG API, FAISS, embeddings, model server)
- Optional cloud standby API disabled until incident
- Reverse proxy + TLS + IP allowlists
- Daily backups of KB, index, and configs

### Monitoring/alerting (minimal overhead)
- Health checks: /health, /chat synthetic probe every 1–5 min
- Alert channels: email + Teams/Slack
- Track:
  - uptime
  - p50/p95 latency
  - model load failures
  - disk usage
  - GPU memory/temperature
- Simple stack: Uptime Kuma + Prometheus/Grafana (or managed equivalent by campus IT)

### Handoff/doc plan (critical for post-graduation continuity)
- 1 runbook with:
  - restart steps
  - rollback steps
  - “if X fails, do Y” decision tree
- 1 architecture diagram
- 1 credentials/secrets ownership sheet (institution-controlled, not personal accounts)
- quarterly 30-min tabletop failover drill

### No-code KB updates
Build an internal admin page:
- Upload PDF/TXT
- Auto-extract/clean/chunk/embed
- Rebuild FAISS index
- Version + publish button
- Validation preview before publish

This removes engineering dependency for content updates.

## Final Decision
If this were my call for CBU Campus Store long-term:
1. Deploy on-prem primary now with a single GPU machine.
2. Keep Firebase frontend unchanged.
3. Use Qwen2.5-7B-Instruct primary + Phi-4-mini fallback.
4. Add cloud standby only for DR.
5. Deliver runbooks/admin KB UI before internship handoff.

## Sources
- AWS EC2 G4 instances/pricing examples: https://aws.amazon.com/ec2/instance-types/g4/
- AWS Compute SLA: https://aws.amazon.com/compute/sla/
- Google Cloud GPU pricing: https://cloud.google.com/compute/gpus-pricing
- Google Compute SLA: https://cloud.google.com/compute/sla
- Azure VM pricing page (N-series “starting from”): https://azure.microsoft.com/en-us/pricing/details/virtual-machines/linux/
- Azure VM availability statement: https://azure.microsoft.com/en-us/products/virtual-machines
- DigitalOcean GPU pricing: https://www.digitalocean.com/pricing/gpu-droplets
- DigitalOcean Droplet SLA: https://www.digitalocean.com/sla/cpu-droplets
- Hetzner GPU servers: https://www.hetzner.com/dedicated-rootserver/matrix-gpu/
- Akamai/Linode pricing page: https://www.akamai.com/cloud/pricing
- Firebase Hosting: https://firebase.google.com/products/hosting/
- Firestore pricing: https://firebase.google.com/docs/firestore/pricing
- FERPA “education record” definition reference: https://studentprivacy.ed.gov/faq/what-education-record
- Llama 3.1 model card/license pointer: https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct
- Llama 3.1 license text: https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_1/LICENSE
- Llama 3.3 license text: https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_3/LICENSE
- Mistral 7B Instruct v0.3: https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3
- Phi-4: https://huggingface.co/microsoft/phi-4
- Phi-4-mini-instruct: https://huggingface.co/microsoft/Phi-4-mini-instruct
- Phi-3 ONNX throughput example: https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx
- Gemma 2 model page / gated terms: https://huggingface.co/google/gemma-2-9b-it and https://ai.google.dev/gemma/terms
- Qwen2.5-7B-Instruct: https://huggingface.co/Qwen/Qwen2.5-7B-Instruct
- DeepSeek-R1-Distill-Qwen-7B: https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-7B
- NVIDIA RTX 6000 Ada listing: https://marketplace.nvidia.com/en-us/enterprise/laptops-workstations/nvidia-rtx-6000-ada-generation/
- Apple Mac Studio pricing/specs/power: https://www.apple.com/shop/buy-mac/mac-studio and https://support.apple.com/102027
- California electricity profile (EIA): https://www.eia.gov/electricity/state/California/
