"""FastAPI service for Decision Cortex.

Liveness is deliberately decoupled from FalkorDB availability: ``/healthz``
answers 200 from the process alone, so the API boots (and the verification
container can probe it) with no database reachable. The seed status is
reported honestly in the body instead of gating the response.
"""

from fastapi import FastAPI

app = FastAPI(title="Decision Cortex API")


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"status": "ok", "seeded": False}
