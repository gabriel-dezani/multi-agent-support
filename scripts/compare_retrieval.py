"""Run real Chroma dense-vs-hybrid retrieval comparison; no synthetic claims.

Requires a locally populated Chroma index. With the normal OpenAI embedding
provider this command MAY invoke a paid API; it is intentionally NOT part of
the zero-cost CI. Prefer local fixed-embedding integration tests for CI.
"""
import argparse
import hashlib
import json
from pathlib import Path

from app.evaluation.paired_retrieval import paired_report, ablation_gate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', default='retrieval_ablation.json')
    parser.add_argument('--k', type=int, default=4)
    parser.add_argument('--minimum', type=int, default=10)
    args = parser.parse_args()
    data = Path(args.dataset).read_bytes()
    items = json.loads(data)
    from app.rag.retriever import KnowledgeRetriever
    retriever = KnowledgeRetriever()
    report = paired_report(items,
        lambda q: retriever.retrieve(q, hybrid_enabled=False),
        lambda q: retriever.retrieve(q, hybrid_enabled=True),
        k=args.k, minimum=args.minimum)
    report['dataset_sha256'] = hashlib.sha256(data).hexdigest()
    report['gates_failed'] = ablation_gate(report, minimum=args.minimum)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if report['gates_failed']:
        raise SystemExit('Retrieval quality gate failed: ' + ', '.join(report['gates_failed']))


if __name__ == '__main__':
    main()
