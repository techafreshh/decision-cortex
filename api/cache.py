"""In-process response cache for the scripted demo scenarios.

The four PRD §10 scenario buttons must be deterministic and free on replay:
the first call computes an :class:`~api.answer.AnswerPlan` and stores it under
the scenario name; later calls replay that plan without re-running the S1/S2
models (zero ``reason`` calls). Free questions are never cached — caching them
would mask regressions and buy nothing.

The cache is process-local and dies with the server, so a code change cannot
serve a stale plan across a restart. Guarded by a lock because uvicorn serves
requests from multiple threads: :meth:`ScenarioCache.get_or_compute` holds a
per-scenario lock across the compute so a cold-cache double-click cannot run
two S2 pipelines for the same scenario.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.answer import AnswerPlan


class ScenarioCache:
    """A lock-guarded ``scenario name -> AnswerPlan`` map."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plans: dict[str, AnswerPlan] = {}
        self._computing: dict[str, threading.Lock] = {}

    def get(self, scenario: str) -> AnswerPlan | None:
        with self._lock:
            return self._plans.get(scenario)

    def put(self, scenario: str, plan: AnswerPlan) -> None:
        with self._lock:
            self._plans[scenario] = plan

    def get_or_compute(
        self, scenario: str, factory: Callable[[], AnswerPlan]
    ) -> tuple[AnswerPlan, bool]:
        """Return the cached plan, computing and caching it once if absent.

        The factory runs under a per-scenario lock, so two concurrent first
        requests cannot both compute — the second waits and replays, spending
        no S2 budget. Returns ``(plan, computed)``: ``computed`` is ``True``
        only for the request that ran the factory.
        """
        with self._lock:
            plan = self._plans.get(scenario)
            if plan is not None:
                return plan, False
            compute_lock = self._computing.setdefault(scenario, threading.Lock())
        with compute_lock:
            with self._lock:
                plan = self._plans.get(scenario)
                if plan is not None:
                    return plan, False
            plan = factory()
            with self._lock:
                self._plans[scenario] = plan
            return plan, True

    def clear(self) -> None:
        with self._lock:
            self._plans.clear()


cache = ScenarioCache()
