# Decision Cortex API image: FastAPI + the offline snapshot loader.
#
# Build context is the repo root (compose sets `context: ..`) so the image can
# copy `ingest/` and `snapshot/` alongside the installed `api` package. The
# published wheel stays `api`-only (pyproject.toml); the container resolves
# `import ingest` through PYTHONPATH=/app at runtime instead of packaging it.
#
# Two stages so the C toolchain never reaches the runtime image. `build-essential`
# is required, not optional: `hnswlib`, a transitive `graphrag-sdk` dependency,
# ships sdist-only and compiles at install time.
FROM python:3.12-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml ./
COPY api ./api
# torch must be installed from the CPU-only index before `.[faithfulness]`: the
# default PyPI linux wheel drags the whole CUDA stack (several GB) into a
# CPU-only deployment. The extra then sees torch already satisfied.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir '.[faithfulness]'

FROM python:3.12-slim AS runtime

COPY --from=build /opt/venv /opt/venv
# PYTHONPATH=/app is what makes `import ingest` work without packaging it; the
# seed entrypoint (`python -m api.seed`) and the loader both need it.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY ingest ./ingest
COPY snapshot ./snapshot
# GET /verification reads the pinned 40-question set in place.
COPY verification ./verification

EXPOSE 8000
# Compose overrides this with the seed-then-exec command; the bare uvicorn
# start keeps the image runnable on its own (graph must already be seeded).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
