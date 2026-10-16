"""Provider billing/config outages are technical failures, not human tickets."""
import pytest
from app.core.upstream import UpstreamUnavailable, classify_provider_error


class FakeProviderError(Exception):
    def __init__(self, code):
        self.code = code
        self.body = {'error': {'code': code}}


@pytest.mark.parametrize('code', ['credit_balance_exhausted','insufficient_quota',
                                  'invalid_api_key','rate_limit_exceeded'])
def test_provider_incidents_are_identified_without_request_text(code):
    assert classify_provider_error(FakeProviderError(code))


def test_generic_exception_does_not_count_as_billing_outage():
    assert not classify_provider_error(RuntimeError('unrecognized network problem'))


def test_nested_api_body_can_be_classified():
    class Error(Exception):
        body = {'error': {'code': 'credit_balance_exhausted'}}
    assert classify_provider_error(Error())


def test_router_rejects_provider_quota_failure_without_creating_human_ticket(monkeypatch):
    from app.agents.router import RouterAgent
    router = RouterAgent(enable_llm=True)
    def raise_quota(*args, **kwargs):
        raise FakeProviderError('credit_balance_exhausted')
    monkeypatch.setattr(router, '_route_llm', raise_quota)
    with pytest.raises(UpstreamUnavailable):
        router.route('Explique o Pix Getnet', 'customer', [])
