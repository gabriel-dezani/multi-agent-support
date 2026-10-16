import pytest
from app.core.observability import (safe_trace_attributes, evaluate_slo,
                                    validate_otlp_url, export_structured_trace)


def test_otlp_export_never_receives_unapproved_fields():
    safe = safe_trace_attributes({'message': 'sensitive account number',
                                  'answer': 'private', 'user_id': 'real-customer',
                                  'status': 'ok', 'duration_ms': 4.2,
                                  'agent': 'knowledge'})
    assert safe == {'status':'ok', 'duration_ms': 4.2, 'agent':'knowledge'}


def test_slo_must_not_report_false_green_with_tiny_sample():
    assert evaluate_slo({'requests':0,'error_rate':0,'latency_p95_ms':0})['status'] == 'insufficient_data'
    assert evaluate_slo({'requests':30,'error_rate':0.01,'latency_p95_ms':1000})['status'] == 'pass'
    assert evaluate_slo({'requests':30,'error_rate':0.12,'latency_p95_ms':1000})['status'] == 'fail'
    assert evaluate_slo({'requests':30,'error_rate':0.01,'latency_p95_ms':None})['status'] == 'fail'


def test_invalid_otlp_endpoints_fail_closed():
    for endpoint in ['http://bad.example/v1/traces', 'https://user:password@bad.example/v1/traces',
                     'https://bad.example/v1/traces?token=secret', 'file:///v1/traces']:
        with pytest.raises(ValueError):
            validate_otlp_url(endpoint, 'production')
    assert validate_otlp_url('http://otel-collector:4318/v1/traces','development')
    assert validate_otlp_url('https://collector.example/v1/traces','production')
