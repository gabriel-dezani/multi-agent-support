import pytest
pytest.importorskip('langchain_core')
pytest.importorskip('langchain_text_splitters')
from app.rag.ingestion import _valid_url


@pytest.mark.parametrize('url,allowed',[
    ('https://www.getnet.net/en',True),
    ('https://site.getnet.com.br/crediario/',True),
    ('http://site.getnet.com.br/crediario/',False),
    ('https://site.getnet.com.br.evil.org/steal',False),
    ('https://127.0.0.1/',False),
    ('https://site.getnet.com.br:444/path',False),
    ('https://attacker@site.getnet.com.br/path',False),
])
def test_https_allowlist_is_strict(url,allowed):
    assert _valid_url(url) is allowed
