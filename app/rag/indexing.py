"""Idempotent Chroma replacement per URL without retaining outdated chunks.

Existing chunks are only removed AFTER the new version was successfully
upserted. Metadata source_url is the ownership key and IDs are stable across
re-ingestion even when the page text changes.
"""
from hashlib import sha256
from app.rag.ingestion import _valid_url


def stable_chunk_id(url: str, index: int) -> str:
    if index < 0:
        raise ValueError("index must be nonnegative")
    return sha256(f"{url}::{index}".encode("utf-8")).hexdigest()


def upsert_source(store, url: str, docs: list) -> tuple[int, int]:
    if not _valid_url(url):
        raise ValueError("URL HTTPS Getnet não autorizada")
    if not docs:
        raise ValueError("source has no usable chunks")
    ids = [stable_chunk_id(url, n) for n in range(len(docs))]
    # Validate the entire replacement before touching metadata or stored content.
    for doc in docs:
        if doc.metadata.get("source_url") != url:
            raise ValueError("chunk belongs to another URL")
        if not isinstance(doc.page_content, str) or not doc.page_content.strip():
            raise ValueError("chunk has no usable content")
    for doc, doc_id in zip(docs, ids):
        doc.metadata["chunk_id"] = doc_id
    old = set(store.get(where={"source_url": url}, include=[]).get("ids", []))
    store.add_documents(docs, ids=ids)
    stale = old.difference(ids)
    if stale:
        store.delete(ids=sorted(stale))
    return len(ids), len(stale)
