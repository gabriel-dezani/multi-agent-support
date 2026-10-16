"""Integration contracts added after the 9.2 feedback; no paid API calls."""
import pytest

pytest.importorskip('structlog')
pytest.importorskip('langgraph')

from app.main import app
from app.rag.retriever import normalized_relevance


def test_floating_point_overshoot_is_bounded_for_chroma():
    raw = [
        ('exact-match', 1.0000000238418578),
        ('similar', 0.3600000200271607),
        ('bad', float('nan')),
        ('unreasonable', 1.7),
        ('negative-precision', -0.00000001),
    ]
    scores = normalized_relevance(raw)
    assert scores == [('exact-match', 1.0), ('similar', 0.3600000200271607),
                      ('negative-precision', 0.0)]
    assert all(0 <= score <= 1 for _, score in scores)


def test_swagger_has_bearer_authentication_without_header_text_field():
    schema = app.openapi()
    security = schema['components']['securitySchemes']['BearerAuth']
    assert security['type'] == 'http'
    assert security['scheme'] == 'bearer'
    chat = schema['paths']['/chat']['post']
    assert {'BearerAuth': []} in chat['security']
    header_fields = [field['name'].lower() for field in chat.get('parameters', [])
                     if field['in'] == 'header']
    assert 'authorization' not in header_fields
