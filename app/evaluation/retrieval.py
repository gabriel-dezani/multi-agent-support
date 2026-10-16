"""Grounded retrieval and answer-evaluation metrics; no LLM or private data."""
from urllib.parse import urlsplit, parse_qsl, urlencode


def normalize_source(url: str) -> str:
    """Normalize *only for comparison*; never use the result for URL access."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except (ValueError, TypeError, AttributeError):
        return ""
    if (parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password
            or port not in (None, 443) or any(c.isspace() for c in url)):
        return ""
    host = parts.hostname.lower().removeprefix("www.")
    # Paths and query values may be case sensitive or select different pages.
    # Fragments identify a section of the same document and are ignored.
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                       if key.lower() != 'ref' and not key.lower().startswith('utm_')])
    return host + parts.path.rstrip("/") + ("?" + query if query else "")


def metrics_at_k(gold_sources: list[str], retrieved_sources: list[str], k: int) -> dict:
    """Recall, precision, hit-rate, MRR (and nDCG) against human-curated sources.

    Missing gold labels do not score as failures or successes. Such cases should
    be excluded from metric denominators and reported separately by the gate.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    gold = {normalize_source(url) for url in gold_sources} - {""}
    # Preserve original positions. An invalid source at rank 1 cannot make a
    # correct URL at rank 2 count as rank 1 (MRR/nDCG must be honest).
    selected = [normalize_source(url) for url in retrieved_sources[:k]]
    if not gold:
        raise ValueError("at least one valid gold source required")
    unique_hits = len(gold.intersection(selected))
    first_rank = next((i for i, url in enumerate(selected, 1) if url in gold), None)
    import math
    dcg = sum(1 / math.log2(rank + 1) for rank, url in enumerate(selected, 1)
              if url in gold and url not in selected[:rank-1])
    idcg = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(gold)) + 1))
    return {
        "recall_at_k": round(unique_hits / len(gold), 4),
        "precision_at_k": round(unique_hits / k, 4),
        "hit_at_k": float(bool(unique_hits)),
        "mrr": round(1 / first_rank, 4) if first_rank else 0.0,
        "ndcg_at_k": round(dcg / idcg, 4) if idcg else 0.0,
    }


def aggregate_scores(items: list[dict[str, float]]) -> dict[str, float]:
    if not items:
        raise ValueError("no labeled evaluations")
    keys = ("recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k")
    return {key: round(sum(item[key] for item in items) / len(items), 4) for key in keys}


def evaluate_retrieval_items(items: list[dict], retrieve, *, k: int = 5) -> dict:
    """Execute a real retriever. Errors count as failures, not skipped cases."""
    results = []
    skipped = 0
    seen = set()
    for item in items:
        identifier = str(item.get("id", ""))
        if not identifier or identifier in seen:
            raise ValueError("dataset IDs must be unique and nonempty")
        seen.add(identifier)
        gold = item.get("gold_source_urls") or []
        if not gold:
            skipped += 1
            continue
        if not isinstance(gold, list) or not all(isinstance(url, str) for url in gold):
            raise ValueError("invalid gold_source_urls")
        try:
            found = retrieve(item["question"])
            sources = [doc.metadata.get("source_url", "") for doc, _ in found]
            scores = metrics_at_k(gold, sources, k)
            status = "ok"
        except Exception as exc:
            scores = dict.fromkeys(("recall_at_k", "precision_at_k", "hit_at_k", "mrr", "ndcg_at_k"), 0.0)
            status = "retrieval_error:" + type(exc).__name__
        results.append({"id": identifier, "status": status, **scores})
    if not results:
        raise ValueError("no eligible labeled evaluation items")
    return {"evaluated": len(results), "unlabeled": skipped,
            "scores": aggregate_scores(results), "cases": results}


def check_gates(report: dict, thresholds: dict[str, float], *, minimum_cases: int = 5) -> list[str]:
    violations = []
    if report["evaluated"] < minimum_cases:
        violations.append(f"expected at least {minimum_cases} labeled cases, got {report['evaluated']}")
    for key, threshold in thresholds.items():
        if key not in report["scores"]:
            raise ValueError("unsupported gate: " + key)
        if report["scores"][key] < threshold:
            violations.append(f"{key}={report['scores'][key]} below {threshold}")
    return violations


def compare_retrievers(items, retrievers, *, k=4, human_reviewed=False):
    """Evaluate all modes on identical labels, with explicit provenance.

    Metadata requirements do not authenticate a reviewer. Synthetic labels must
    remain synthetic even when the underlying storage/retrieval is real.
    """
    if human_reviewed:
        from app.evaluation.paired_retrieval import verify_reviewed_dataset
        verify_reviewed_dataset(items)
    return {'human_reviewed':human_reviewed,
            'scope':'review_metadata_supplied' if human_reviewed else 'developer_synthetic',
            'k':k, 'modes':{name:evaluate_retrieval_items(items,retrieve,k=k)
                           for name,retrieve in retrievers.items()}}
