"""Meaningful offline regression gates for telemetry and local readiness.

No OpenAI, OTLP exporter or other external service is contacted.
"""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
import math
import sqlite3

import pytest

from app.core import observability
from app.core.observability import evaluate_slo, safe_trace_attributes
from app.core.readiness import check_readiness, validate_deployment


def test_slo_uses_raw_counts_instead_of_rounded_display_rate():
    # 11/219 = 5.0228%: a true violation, even if the UI rate is rounded to 5%.
    report = evaluate_slo({"requests": 219, "errors": 11, "error_rate": 0.05,
                           "latency_p95_ms": 1100})
    assert report["status"] == "fail"
    assert report["checks"]["error_rate"] is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01, 1.1, True, "0.01"])
def test_slo_fails_closed_on_untrusted_error_rates(bad):
    assert evaluate_slo({"requests": 35, "error_rate": bad,
                         "latency_p95_ms": 250})["status"] == "fail"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True, "100"])
def test_slo_fails_closed_on_invalid_latency(bad):
    assert evaluate_slo({"requests": 35, "error_rate": 0,
                         "latency_p95_ms": bad})["status"] == "fail"


def test_slo_without_samples_never_reports_pass():
    assert evaluate_slo({"requests": 10, "errors": 0,
                         "latency_p95_ms": 100})["status"] == "insufficient_data"
    assert evaluate_slo({"requests": "invalid", "error_rate": 0,
                         "latency_p95_ms": 0})["status"] == "insufficient_data"


def test_traces_use_immutable_categories_not_short_pii():
    allowed = safe_trace_attributes({
        "agent": "knowledge", "route": "customer@example.com", "status": "ok",
        "routing_strategy": "deterministic_fallback", "message": "private data",
        "input_tokens": 9, "duration_ms": 0.0, "degraded": True,
        "output_tokens": float("inf"), "retrieval_hits": -3,
        "status_code": "200", "latency_ms": float("nan"),
    })
    assert allowed == {
        "agent": "knowledge", "status": "ok", "routing_strategy": "deterministic_fallback",
        "input_tokens": 9, "duration_ms": 0.0, "degraded": True,
    }
    assert safe_trace_attributes(None) == {}


def test_tracing_is_disabled_without_endpoint(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(otlp_endpoint=""))
    observability.export_structured_trace("not-a-uuid", [{"agent": "knowledge"}], {})
    assert observability.configure_tracing(SimpleNamespace(otlp_endpoint="")) is False


def test_otlp_export_strips_private_data_and_caps_span_count(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(otlp_endpoint="https://collector.example/v1/traces"))
    from opentelemetry import trace
    created = []

    class FakeSpan:
        def __init__(self, name):
            self.name = name
            self.attributes = {}
            created.append(self)

        def set_attribute(self, key, value):
            self.attributes[key] = value

    class FakeTracer:
        @contextmanager
        def start_as_current_span(self, name):
            yield FakeSpan(name)

    monkeypatch.setattr(trace, "get_tracer", lambda name: FakeTracer())
    rid = str(uuid4())
    spans = [{"agent": "account:Jane Doe", "status": "Jane Doe", "duration_ms": -1.0,
              "message": "confidential"}] * 60
    observability.export_structured_trace(rid, spans, {"route": "knowledge", "user_id": "Jane Doe",
                                                          "latency_ms": 200, "status": "private email"})
    assert len(created) == 41  # one root + first 40 bounded children
    assert created[0].attributes == {"request_id": rid, "route": "knowledge", "latency_ms": 200}
    assert all(span.name == "agent.other" and not span.attributes for span in created[1:])


def test_otlp_export_never_exports_unsafe_request_id(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(otlp_endpoint="https://collector.example/v1/traces"))
    from opentelemetry import trace
    attrs = {}

    class FakeSpan:
        def set_attribute(self, name, value):
            attrs[name] = value

    class FakeTracer:
        @contextmanager
        def start_as_current_span(self, name):
            yield FakeSpan()

    monkeypatch.setattr(trace, "get_tracer", lambda name: FakeTracer())
    observability.export_structured_trace("customer-secret-123", [], {})
    assert "request_id" not in attrs


def test_otlp_export_failures_do_not_affect_customer(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(otlp_endpoint="https://collector.example/v1/traces"))
    from opentelemetry import trace

    def fail(name):
        raise RuntimeError("simulated exporter failure")

    monkeypatch.setattr(trace, "get_tracer", fail)
    observability.export_structured_trace(str(uuid4()), [], {})


def test_readiness_does_not_create_tables_or_missing_db(tmp_path):
    db = tmp_path / "state.db"
    vectors = tmp_path / "vectors"
    vectors.mkdir()
    settings = SimpleNamespace(state_db_path=str(db), vector_store_path=str(vectors))
    assert not check_readiness(settings)
    assert not db.exists()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE customer_memory (id INTEGER PRIMARY KEY)")
    assert not check_readiness(settings)  # an arbitrary table is insufficient
    with sqlite3.connect(db) as conn:
        names = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"customer_memory"}
    from app.memory.store import ConversationMemoryStore
    from app.handoff.repository import HandoffRepository
    from app.core.telemetry import TelemetryRepository
    ConversationMemoryStore(str(db))
    HandoffRepository(str(db))
    TelemetryRepository(str(db))
    assert check_readiness(settings)


def test_prod_readiness_rejects_partial_operational_setup():
    settings = SimpleNamespace(app_env="production", auth_mode="oidc",
                               oidc_issuer="", oidc_jwks_url="", oidc_audience="",
                               rag_verifier_mode="llm", otlp_endpoint="")
    with pytest.raises(RuntimeError, match="OIDC"):
        validate_deployment(settings)
    settings.oidc_issuer = "https://identity.example/"
    settings.oidc_jwks_url = "https://identity.example/jwks"
    settings.oidc_audience = "multi-agent-support"
    settings.rag_verifier_mode = "heuristic"
    with pytest.raises(RuntimeError, match="RAG_VERIFIER_MODE"):
        validate_deployment(settings)
    settings.rag_verifier_mode = "llm"
    with pytest.raises(RuntimeError, match="OTLP"):
        validate_deployment(settings)


def test_invalid_production_modes_are_rejected_at_config_load():
    from pydantic import ValidationError
    from app.core.config import Settings

    for field, value in (("app_env", "Production"), ("app_env", "prod"),
                         ("auth_mode", "none"), ("rag_verifier_mode", "skip")):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: value})


def test_slo_refuses_inconsistent_error_counts_even_if_display_rate_is_green():
    stats = {"requests": 30, "errors": 300, "error_rate": 0.0,
             "latency_p95_ms": 100}
    assert evaluate_slo(stats)["status"] == "fail"


def test_otlp_configuration_is_optional_if_sdk_is_missing(monkeypatch):
    import builtins
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name == "opentelemetry.sdk.resources":
            raise ImportError("simulated missing optional OTLP SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)
    settings = SimpleNamespace(otlp_endpoint="https://collector.example/v1/traces",
                               app_env="production", otlp_service_name="support")
    assert observability.configure_tracing(settings) is False


def test_otlp_configuration_batches_without_sending_any_network_requests(monkeypatch):
    import sys
    import types
    from opentelemetry import trace

    configs = []

    class FakeResource:
        @staticmethod
        def create(attrs):
            return attrs

    class FakeTracerProvider:
        def __init__(self, resource):
            self.resource = resource
            self.processors = []
            configs.append(self)

        def add_span_processor(self, processor):
            self.processors.append(processor)

    class FakeSpanProcessor:
        def __init__(self, exporter, **kwargs):
            self.exporter = exporter
            self.kwargs = kwargs

    class FakeExporter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def install_module(name, **attributes):
        module = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)

    install_module("opentelemetry.sdk.resources", Resource=FakeResource)
    install_module("opentelemetry.sdk.trace", TracerProvider=FakeTracerProvider)
    install_module("opentelemetry.sdk.trace.export", BatchSpanProcessor=FakeSpanProcessor)
    install_module("opentelemetry.exporter.otlp.proto.http.trace_exporter", OTLPSpanExporter=FakeExporter)
    monkeypatch.setattr(trace, "set_tracer_provider", lambda provider: configs.append("registered"))

    settings = SimpleNamespace(otlp_endpoint="https://collector.example/v1/traces",
                               app_env="production", otlp_service_name="support")
    assert observability.configure_tracing(settings)
    provider = configs[0]
    assert provider.resource == {"service.name": "support"}
    assert provider.processors[0].kwargs["max_queue_size"] == 2048
    assert provider.processors[0].exporter.kwargs == {
        "endpoint": "https://collector.example/v1/traces", "timeout": 3,
    }
    assert configs[1] == "registered"
