from types import SimpleNamespace
import pytest
from app.rag.indexing import upsert_source, stable_chunk_id


class FakeStore:
    def __init__(self):
        self.docs = {}
        self.broken = False

    def get(self, where=None, include=None):
        return {"ids": [i for i, d in self.docs.items()
                        if d.metadata["source_url"] == where["source_url"]]}

    def add_documents(self, docs, ids):
        if self.broken:
            raise RuntimeError("embedding service down")
        self.docs.update(zip(ids, docs))

    def delete(self, ids):
        for i in ids:
            self.docs.pop(i, None)


def docs(url, *contents):
    return [SimpleNamespace(page_content=content, metadata={"source_url": url})
            for content in contents]


def test_reingestion_replaces_existing_content_and_removes_stale():
    store = FakeStore()
    url = "https://www.getnet.net/en"
    assert upsert_source(store, url, docs(url, "old 1", "old 2")) == (2, 0)
    assert upsert_source(store, url, docs(url, "new")) == (1, 1)
    assert list(store.docs) == [stable_chunk_id(url, 0)]
    assert next(iter(store.docs.values())).page_content == "new"


def test_failed_new_embedding_does_not_delete_prior_chunks():
    store = FakeStore()
    url = "https://site.getnet.com.br/pix/"
    upsert_source(store, url, docs(url, "original", "original 2"))
    store.broken = True
    with pytest.raises(RuntimeError):
        upsert_source(store, url, docs(url, "replacement"))
    assert len(store.docs) == 2


def test_cross_source_isolation_and_validation():
    store = FakeStore()
    a, b = "https://www.getnet.net/en", "https://site.getnet.com.br/pix/"
    upsert_source(store, a, docs(a, "a1", "a2"))
    upsert_source(store, b, docs(b, "b1"))
    upsert_source(store, a, docs(a, "a1-new"))
    assert len(store.docs) == 2
    assert store.docs[stable_chunk_id(b, 0)].page_content == "b1"
    with pytest.raises(ValueError):
        upsert_source(store, a, docs(b, "wrong owner"))


@pytest.mark.parametrize("url", [
    "https://evil.example/pix/",
    "http://site.getnet.com.br/pix/",
    "https://site.getnet.com.br.evil.example/pix/",
    "https://127.0.0.1/",
    "https://user@site.getnet.com.br/pix/",
    "https://site.getnet.com.br:444/pix/",
])
def test_direct_indexing_rejects_unauthorized_urls_before_writes(url):
    store = FakeStore()
    with pytest.raises(ValueError, match="URL HTTPS"):
        upsert_source(store, url, docs(url, "pix"))
    assert store.docs == {}


@pytest.mark.parametrize("contents", [(), ("",), ("   ",), (None,), ("valid new", " ")])
def test_invalid_replacement_preserves_all_previous_chunks(contents):
    store = FakeStore()
    url = "https://site.getnet.com.br/pix/"
    upsert_source(store, url, docs(url, "old one", "old two"))
    replacement = docs(url, *contents)
    with pytest.raises(ValueError, match="usable"):
        upsert_source(store, url, replacement)
    assert [doc.page_content for doc in store.docs.values()] == ["old one", "old two"]
    assert all("chunk_id" not in doc.metadata for doc in replacement)
