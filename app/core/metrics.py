from collections import Counter, deque
from threading import Lock


class MetricsRegistry:
    def __init__(self):
        self._lock = Lock()
        self._requests = 0
        self._errors = 0
        self._handoffs = 0
        self._handoffs_resolved = 0
        self._degraded = 0
        self._multi_agent = 0
        self._routes = Counter()
        self._agents = Counter()
        self._routing_strategies = Counter()
        self._plan_lengths = Counter()
        self._latencies_ms = deque(maxlen=1000)
        self._handoff_resolution_seconds = deque(maxlen=1000)

    def record(
        self,
        *,
        route: str | None,
        agents: list[str] | None,
        handoff: bool,
        latency_ms: float,
        error: bool = False,
        degraded: bool = False,
        plan: list[str] | None = None,
        routing_strategy: str | None = None,
    ) -> None:
        with self._lock:
            self._requests += 1
            self._errors += int(error)
            self._handoffs += int(handoff)
            self._degraded += int(degraded)
            plan = plan or []
            self._multi_agent += int(len(plan) > 1)
            self._plan_lengths[len(plan)] += 1
            if route:
                self._routes[route] += 1
            if routing_strategy:
                self._routing_strategies[routing_strategy] += 1
            for agent in agents or []:
                self._agents[agent] += 1
            self._latencies_ms.append(float(latency_ms))

    def record_handoff_resolution(self, resolution_seconds: float | None = None) -> None:
        with self._lock:
            self._handoffs_resolved += 1
            if resolution_seconds is not None and resolution_seconds >= 0:
                self._handoff_resolution_seconds.append(float(resolution_seconds))

    @staticmethod
    def _percentile(values, p: float) -> float:
        values = sorted(values)
        if not values:
            return 0.0
        idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
        return round(values[idx], 2)

    def snapshot(self) -> dict:
        with self._lock:
            requests = self._requests
            return {
                "requests_total": requests,
                "errors_total": self._errors,
                "error_rate": round(self._errors / requests, 4) if requests else 0.0,
                "handoffs_total": self._handoffs,
                "handoffs_resolved_total": self._handoffs_resolved,
                "handoff_rate": round(self._handoffs / requests, 4) if requests else 0.0,
                "degraded_requests_total": self._degraded,
                "multi_agent_requests_total": self._multi_agent,
                "multi_agent_rate": round(self._multi_agent / requests, 4) if requests else 0.0,
                "routes": dict(self._routes),
                "agents": dict(self._agents),
                "routing_strategies": dict(self._routing_strategies),
                "plan_lengths": {str(k): v for k, v in self._plan_lengths.items()},
                "latency_ms": {
                    "p50": self._percentile(self._latencies_ms, 0.50),
                    "p95": self._percentile(self._latencies_ms, 0.95),
                    "p99": self._percentile(self._latencies_ms, 0.99),
                },
                "handoff_resolution_seconds": {
                    "p50": self._percentile(self._handoff_resolution_seconds, 0.50),
                    "p95": self._percentile(self._handoff_resolution_seconds, 0.95),
                    "p99": self._percentile(self._handoff_resolution_seconds, 0.99),
                },
            }


metrics = MetricsRegistry()
