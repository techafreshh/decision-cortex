"""In-process response cache for the scripted demo scenarios.

The four PRD §10 scenario buttons must be deterministic and free on replay:
the first call computes an :class:`~api.answer.AnswerPlan` and stores it under
the scenario name; later calls replay that plan without re-running the S1/S2
models (zero ``reason`` calls). Free questions are never cached — caching them
would mask regressions and buy nothing.

The cache is process-local and dies with the server, so a code change cannot
serve a stale plan across a restart. Guarded by a lock because uvicorn serves
requests from multiple threads.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.answer import AnswerPlan


class ScenarioCache:
    """A lock-guarded ``scenario name -> AnswerPlan`` map."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plans: dict[str, AnswerPlan] = {}

    def get(self, scenario: str) -> AnswerPlan | None:
        with self._lock:
            return self._plans.get(scenario)

    def put(self, scenario: str, plan: AnswerPlan) -> None:
        with self._lock:
            self._plans[scenario] = plan

    def clear(self) -> None:
        with self._lock:
            self._plans.clear()


cache = ScenarioCache()
