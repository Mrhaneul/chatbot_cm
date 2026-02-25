# ── Stage 1: Builder ──────────────────────────────────────────────────────
# Install dependencies in a separate stage to keep the final image lean.
FROM python:3.11-slim AS builder

WORKDIR /install

# Install build tools needed for faiss-cpu and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install/deps --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install/deps /usr/local

# Copy application code
COPY app/ ./app/
COPY data/ ./data/

# Firebase service account is sensitive — it must be mounted at runtime,
# not baked into the image. See docker-compose.yml for the volume mount.
# Do NOT copy app/firebase-service-account.json here.

# Expose FastAPI port
EXPOSE 8000

# Non-root user for security
RUN useradd -m -u 1000 lance && chown -R lance:lance /app
USER lance

# Health check — uses the existing /sessions/stats endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/sessions/stats')"

# Start the backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]