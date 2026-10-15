"""Real RAG retrieval gate; exits non-zero on quality regressions or errors.

Requires populated Chroma and a reviewed gold-source dataset. Never claim
live quality from structurally mocked data.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path

from app.evaluation.retrieval import check_gates, evaluate_retrieval_items


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--dataset", required=True, help="JSON array of {id, question, gold_source_urls}")
    cli.add_argument("--output", default="retrieval_metrics.json")
    cli.add_argument("--k", type=int, default=4)
    cli.add_argument("--min-cases", type=int, default=5)
    cli.add_argument("--min-recall", type=float, default=0.8)
    cli.add_argument("--min-mrr", type=float, default=0.75)
    cli.add_argument("--min-hit", type=float, default=0.9)
    args = cli.parse_args()
    if args.k < 1 or args.min_cases < 1:
        cli.error("k and min-cases must be positive")
    source = Path(args.dataset).read_bytes()
    items = json.loads(source)
    if not isinstance(items, list):
        cli.error("dataset must be an array")
    for item in items:
        if not isinstance(item, dict):
            cli.error("Every item must be an object")
        if item.get("gold_source_urls") and (not item.get("reviewed_by") or not item.get("reviewed_at")):
            cli.error("Gold source labels require reviewed_by and reviewed_at from a human")
    from app.rag.retriever import KnowledgeRetriever
    engine = KnowledgeRetriever()
    report = evaluate_retrieval_items(items, engine.retrieve, k=args.k)
    report["dataset_sha256"] = hashlib.sha256(source).hexdigest()
    report["methodology"] = "Real Chroma retrieval; manually reviewed golden source URLs; deterministic metrics"
    report["gates"] = {"recall_at_k": args.min_recall, "mrr": args.min_mrr,
                       "hit_at_k": args.min_hit, "minimum_cases": args.min_cases}
    report["violations"] = check_gates(report, {"recall_at_k": args.min_recall,
         "mrr": args.min_mrr, "hit_at_k": args.min_hit}, minimum_cases=args.min_cases)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("%s", json.dumps({"scores": report["scores"], "evaluated": report["evaluated"],
                      "violations": report["violations"]}, ensure_ascii=False))
    if report["violations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
