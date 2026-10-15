"""Optional OTLP traces and explicit SLO gates, without prompts, PII or answers.

Exporters are opt-in. Telemetry failures never change the customer response.
"""
import logging
import math
from uuid import UUID
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


# Only known structural categories are exportable. A length check alone would
# permit a short customer name / account number to leak through a mislabeled
# span attribute. Unrecognized values are dropped rather than generalized.
TRACE_CATEGORIES = {
    "route": frozenset({"knowledge", "customer_support", "web_search", "synthesis",
                         "human_escalation", "blocked", "error", "unknown"}),
    "agent": frozenset({"guardrail", "router", "knowledge", "customer_support",
                         "web_search", "supervisor", "synthesis", "human_escalation",
                         "get_sales_data", "get_terminal_status", "tool:web_search",
                         "blocked", "other"}),
    "status": frozenset({"ok", "blocked", "pending", "resolved", "needs_human",
                          "replan", "unresolved", "fallback", "unknown", "error",
                          "llm_structured_plan", "deterministic_fallback",
                          "deterministic_fallback_after_error"}),
    "routing_strategy": frozenset({"llm_structured_plan", "deterministic_fallback",
                                   "deterministic_fallback_after_error", "pending_handoff"}),
}
TRACE_MEASUREMENTS = frozenset({
    "latency_ms", "duration_ms", "status_code", "escalated", "degraded",
    "agents_count", "input_tokens", "output_tokens", "retrieval_hits",
})


def safe_trace_attributes(data: dict) -> dict:
    """Export only finite nonnegative measurements and fixed category values."""
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, value in data.items():
        if key in TRACE_CATEGORIES and isinstance(value, str):
            if value in TRACE_CATEGORIES[key]:
                out[key] = value
        elif key in TRACE_MEASUREMENTS:
            if isinstance(value, bool):
                if key in {"escalated", "degraded"}:
                    out[key] = value
            elif isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                out[key] = value
    return out


def validate_otlp_url(value: str, environment: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username
            or parts.password or parts.fragment or parts.query or not parts.path.endswith('/v1/traces')):
        raise ValueError('Invalid OTLP trace endpoint')
    if parts.scheme != 'https' and not (
        environment != 'production' and parts.hostname in {'localhost', '127.0.0.1', 'otel-collector'}
    ):
        raise ValueError('OTLP exporter requires HTTPS for external collectors')
    return value


def configure_tracing(settings):
    if not settings.otlp_endpoint:
        return False
    endpoint = validate_otlp_url(settings.otlp_endpoint, settings.app_env)
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider = TracerProvider(resource=Resource.create({'service.name': settings.otlp_service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3),
                           max_queue_size=2048, max_export_batch_size=128))
        trace.set_tracer_provider(provider)
        return True
    except ImportError:
        log.warning('OTLP requested but optional tracing dependencies are unavailable')
        return False


def export_structured_trace(request_id: str, spans: list[dict], properties: dict):
    """Emit already-sanitized, bounded execution steps to the configured tracer."""
    from app.core.config import get_settings
    if not get_settings().otlp_endpoint:
        return
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer('multi-agent-support')
        with tracer.start_as_current_span('chat.request') as parent:
            # Never emit unchecked caller-supplied identifiers as trace labels.
            # Production request IDs are generated UUIDs, not customer values.
            try:
                checked_id = str(UUID(request_id))
            except (TypeError, ValueError, AttributeError):
                checked_id = None
            if checked_id:
                parent.set_attribute('request_id', checked_id)
            for key, value in safe_trace_attributes(properties).items():
                parent.set_attribute(key, value)
            for element in spans[:40]:
                name = element.get('agent', 'unknown')
                if name not in {'guardrail','router','knowledge','customer_support','web_search',
                                'supervisor','synthesis','human_escalation','get_sales_data',
                                'get_terminal_status', 'blocked'}:
                    name = 'other'
                with tracer.start_as_current_span('agent.' + name) as child:
                    attributes = safe_trace_attributes(element)
                    for key, value in attributes.items():
                        child.set_attribute(key, value)
    except Exception as exc:
        log.warning('OTLP export skipped (%s)', type(exc).__name__)


def evaluate_slo(stats: dict, *, minimum_samples: int = 30,
                 max_error_rate: float = 0.05, max_p95_ms: float = 5000) -> dict:
    """Fail closed for missing/out-of-range metrics and use raw error counts.

    ``TelemetryRepository.stats`` rounds its display-only error_rate to four
    decimals, so relying on that field alone may mistakenly admit an SLO
    violation just above a threshold. Raw counts are authoritative when given.
    """
    try:
        sample_count = int(stats.get("requests") or 0)
    except (ValueError, TypeError, OverflowError):
        sample_count = 0
    measured = sample_count >= minimum_samples and minimum_samples > 0
    error_rate = stats.get("error_rate")
    errors = stats.get("errors")
    if errors is not None:
        if (isinstance(errors, int) and not isinstance(errors, bool)
                and sample_count > 0 and 0 <= errors <= sample_count):
            error_rate = errors / sample_count
        else:
            # An inconsistent count must never be overridden by a displayed,
            # possibly rounded, rate in order to report a false PASS.
            error_rate = None
    p95 = stats.get("latency_p95_ms")
    error_valid = (isinstance(error_rate, (float, int))
                   and not isinstance(error_rate, bool)
                   and math.isfinite(error_rate) and 0 <= error_rate <= 1)
    latency_valid = (isinstance(p95, (float, int)) and not isinstance(p95, bool)
                     and math.isfinite(p95) and p95 >= 0)
    checks = {
        "sample_count": measured,
        "error_rate": error_valid and error_rate <= max_error_rate,
        "latency_p95": latency_valid and p95 <= max_p95_ms,
    }
    return {
        "status": "insufficient_data" if not measured else ("pass" if all(checks.values()) else "fail"),
        "checks": checks,
        "sample_count": sample_count,
        "thresholds": {"minimum_samples": minimum_samples,
                       "max_error_rate": max_error_rate, "max_p95_ms": max_p95_ms},
    }


def evaluate_operational_gates(stats: dict, *, minimum_samples: int = 30,
                               max_error_rate: float = 0.05,
                               max_degraded_rate: float = 0.10,
                               max_router_error_rate: float = 0.05,
                               max_p95_ms: float = 5000,
                               min_usage_coverage: float = 0.90,
                               minimum_usage_samples: int = 10) -> dict:
    """Operational alert candidates, not proof of LLM factual correctness.

    Uses raw counts within a fixed UTC window, not lifetime dashboard rates.
    Escalation is reported but NOT a hard quality failure: legitimate customer
    requests may require a human even when the service behaves correctly.
    Missing telemetry or insufficient sample sizes never produce a green PASS.
    This pure function does not send alerts or call external providers.
    """
    config = (minimum_samples, minimum_usage_samples)
    if any(type(value) is not int or value < 1 for value in config):
        raise ValueError("sample minimums must be positive integers")
    for threshold in (max_error_rate, max_degraded_rate, max_router_error_rate, min_usage_coverage):
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold) or not 0 <= threshold <= 1):
            raise ValueError("invalid rate threshold")
    if (isinstance(max_p95_ms, bool) or not isinstance(max_p95_ms, (int, float))
            or not math.isfinite(max_p95_ms) or max_p95_ms <= 0):
        raise ValueError("invalid latency threshold")
    samples = stats.get("requests")
    if type(samples) is not int or samples < 0:
        samples = 0
    measured = samples >= minimum_samples
    checks: dict[str, bool | None] = {}
    for name, count, threshold in (
        ("error_rate", "errors", max_error_rate),
        ("degradation_rate", "degraded", max_degraded_rate),
        ("router_provider_error_rate", "routing_fallback_errors", max_router_error_rate),
    ):
        value = stats.get(count)
        checks[name] = (value / samples <= threshold if measured and type(value) is int
                        and 0 <= value <= samples else None)
    p95 = stats.get("latency_p95_ms")
    checks["latency_p95"] = (p95 <= max_p95_ms if measured and isinstance(p95, (float,int))
                             and not isinstance(p95, bool) and math.isfinite(p95) and p95 >= 0 else None)
    coverage_count = stats.get("usage_evaluated_requests")
    covered = stats.get("usage_complete_requests")
    if type(coverage_count) is int and coverage_count >= minimum_usage_samples:
        checks["usage_completeness"] = (type(covered) is int and 0 <= covered <= coverage_count
                                       and covered / coverage_count >= min_usage_coverage)
    else:
        checks["usage_completeness"] = None
    # Degradation, provider failure, errors and latency are actionable alert
    # conditions. Token coverage is separately assessed for data quality.
    operational = ("error_rate", "degradation_rate", "router_provider_error_rate", "latency_p95")
    alerts = [key for key in operational if checks[key] is False]
    if checks["usage_completeness"] is False:
        alerts.append("usage_completeness")
    unknown = [key for key in operational if checks[key] is None]
    if checks["usage_completeness"] is None:
        unknown.append("usage_completeness")
    status = ("alert" if alerts else
              "insufficient_data" if not measured or unknown else "healthy")
    return {
        "status": status, "window_minutes": stats.get("window_minutes"),
        "sample_count": samples, "alerts": alerts,
        "missing_metrics": unknown, "checks": checks,
        "human_escalations": stats.get("human_escalations"),
        "notes": "Status operacional por janela; não mede factualidade de respostas nem envia notificações.",
    }
