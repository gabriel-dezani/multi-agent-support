"""Bounded, explainable hybrid search: dense recall + BM25 + reciprocal rank fusion.

No external data is transmitted to a reranker. Scores here rank candidates; they
are NOT factuality or grounding probabilities. URL validation and response-level
citations remain mandatory outside this module.
"""
from collections import Counter
from dataclasses import dataclass
import math
import re
from urllib.parse import urlsplit

_TOKEN = re.compile(r"[\wÀ-ÿ]{2,}", flags=re.UNICODE)


def tokenize(value: str) -> list[str]:
    return _TOKEN.findall((value or "").casefold())


def document_key(document) -> str:
    metadata = getattr(document, "metadata", {}) or {}
    return str(metadata.get("chunk_id") or metadata.get("content_hash") or (
        str(metadata.get("source_url", "")) + "\x00" + str(getattr(document, "page_content", ""))
    ))


def bm25_rank(query: str, documents: list, *, k1: float = 1.2,
              b: float = 0.75) -> list[tuple[object, float]]:
    """BM25 lexical search over a bounded snapshot of the indexed corpus."""
    words = set(tokenize(query))
    if not words or not documents:
        return []
    texts = [tokenize(str(getattr(doc, "page_content", ""))) for doc in documents]
    length = len(texts)
    average = max(sum(map(len, texts)) / length, 1)
    df = Counter(word for tokens in texts for word in set(tokens) if word in words)
    scored = []
    for doc, terms in zip(documents, texts):
        count = Counter(terms)
        score = 0.0
        for word in words:
            freq = count[word]
            if not freq:
                continue
            idf = math.log(1 + (length - df[word] + 0.5) / (df[word] + 0.5))
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * len(terms) / average))
        if score > 0:
            scored.append((doc, score))
    return sorted(scored, key=lambda x: (-x[1], document_key(x[0])))


def hybrid_fuse(dense: list[tuple[object, float]], lexical: list[tuple[object, float]],
                *, limit: int, min_dense_relevance: float, rrf_k: int = 60,
                max_per_source: int = 2, verified_lexical=None) -> list[tuple[object, float]]:
    """Fuse rankings; require dense semantic evidence for every returned chunk.

    Lexical-only admission requires separately verified relevance scores.
    Raw BM25 values never satisfy the semantic safety floor.
    """
    dense_map = {}
    for index, (doc, relevance) in enumerate(dense, 1):
        try:
            confidence = float(relevance)
        except (ValueError, TypeError):
            continue
        if not math.isfinite(confidence) or confidence < min_dense_relevance:
            continue
        key = document_key(doc)
        if key not in dense_map:
            dense_map[key] = (doc, confidence, len(dense_map) + 1)
    dense_keys = set(dense_map)
    for doc, relevance in verified_lexical or []:
        confidence = float(relevance)
        key = document_key(doc)
        if math.isfinite(confidence) and min_dense_relevance <= confidence <= 1 and key not in dense_map:
            dense_map[key] = (doc, confidence, None)
    # Duplicates must not push a chunk's first/best sparse rank down.
    sparse_positions = {}
    for doc, _ in lexical:
        key = document_key(doc)
        if key not in sparse_positions:
            sparse_positions[key] = len(sparse_positions) + 1
    ranking = []
    for key, (doc, confidence, rank) in dense_map.items():
        fused = 1 / (rrf_k + rank) if key in dense_keys else 0
        if key in sparse_positions:
            fused += 1 / (rrf_k + sparse_positions[key])
        ranking.append((doc, confidence, fused))
    # Equal one-channel RRF scores prefer an exact lexical match over an ANN
    # distractor; relevance remains the admission gate, not the fusion score.
    ranking.sort(key=lambda row: (-row[2], sparse_positions.get(document_key(row[0]), math.inf),
                                  -row[1], document_key(row[0])))
    chosen, per_source = [], Counter()
    for doc, confidence, _ in ranking:
        source = (getattr(doc, "metadata", {}) or {}).get("source_url", "")
        if per_source[source] >= max_per_source:
            continue
        chosen.append((doc, confidence))  # Never pass off RRF scores as relevance.
        per_source[source] += 1
        if len(chosen) >= limit:
            break
    # Diversity is a preference, not a hard recall cap. Backfill if the corpus
    # has too few independent sources to serve the requested k.
    if len(chosen) < limit:
        used = {document_key(doc) for doc, _ in chosen}
        for doc, confidence, _ in ranking:
            if document_key(doc) not in used:
                chosen.append((doc, confidence))
                used.add(document_key(doc))
                if len(chosen) >= limit:
                    break
    return chosen
