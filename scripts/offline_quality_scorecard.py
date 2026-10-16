"""No-cost release gate for deterministic regression contracts.

ALL labels are synthetic developer-created invariants, not human adjudications
or evidence of live LLM factuality. Never send questions to paid providers.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
from app.rag.verification import verify_claims
from app.agents.router import RouterAgent
from app.evaluation.retrieval import metrics_at_k

log = logging.getLogger(__name__)


def calculate_scorecard(root: Path = Path(".")) -> dict:
    datafile = root / "data/offline_grounding_regressions.json"
    raw = datafile.read_bytes()
    samples = json.loads(raw)
    failures = []
    n_false_accept = 0
    n_false_reject = 0
    positive = negative = 0
    if len(samples) < 20:
        raise ValueError("At least 20 independent grounding cases are required")
    seen = set()
    for case in samples:
        name = case["id"]
        if not name or name in seen or case.get("dataset_type") != "synthetic-regression":
            raise ValueError("Invalid or duplicate synthetic case ID")
        seen.add(name)
        expected = case["expected_supported"]
        if type(expected) is not bool:
            raise ValueError("expected_supported must be a boolean")
        if expected: positive += 1
        else: negative += 1
        actual, _ = verify_claims(case["answer"],case["evidence"],case["sources"])
        if actual != expected:
            failures.append(name)
            if actual: n_false_accept += 1
            else: n_false_reject += 1
    if positive < 8 or negative < 8:
        raise ValueError("Both supported and unsupported scenarios are needed")
    benchmark = json.loads((root / "data/evaluation_dataset.json").read_text(encoding="utf8"))
    feedback = json.loads((root / "data/evaluation_feedback_v6.json").read_text(encoding="utf8"))
    routing = RouterAgent(enable_llm=False)
    routing_failed = []
    for row in benchmark:
        found = routing.route(row["message"],row["user_id"])["route"]
        if found != row["expected_route"]: routing_failed.append(row.get("id", "unknown"))
    for row in feedback:
        history = [v for u in row.get('previous_users',[]) for v in
                   ({'role':'user','content':u},{'role':'assistant','content':'(resposta anterior)'})]
        found = routing.route(row['message'], 'cliente1988', history=history)['plan']
        if found != row['expected_plan']: routing_failed.append(row['id'])
    # Retrieval metric position regression: an invalid leading URL must not
    # disappear from MRR/nDCG denominators.
    source = 'https://site.getnet.com.br/pix/'
    retrieval_gate = metrics_at_k([source], ['http://insecure.invalid/',source], 3)
    if retrieval_gate['mrr'] != .5:
        failures.append('mrr_rank_regression')
    status = not failures and not routing_failed and n_false_accept == 0
    return {
        'status':'pass' if status else 'fail',
        'scope':'offline_synthetic_contracts_only',
        'external_api_calls':0,
        'human_verified_semantic_accuracy':None,
        'dataset_sha256':hashlib.sha256(raw).hexdigest(),
        'factuality_contract':{'cases':len(samples),'supported':positive,'unsupported':negative,
            'false_accept':n_false_accept,'false_reject':n_false_reject,'failures':failures},
        'routing_contract':{'cases':len(benchmark)+len(feedback),'failures':routing_failed},
        'retrieval_contract':{'mrr_invalid_leading_url':retrieval_gate['mrr']},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',default='offline_quality_scorecard.json')
    args = parser.parse_args()
    scorecard=calculate_scorecard()
    Path(args.output).write_text(json.dumps(scorecard,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    log.info('Offline quality contracts: %s',scorecard['status'])
    log.info('Synthetic factuality cases: %d; routing cases: %d; API calls: 0',
             scorecard['factuality_contract']['cases'],scorecard['routing_contract']['cases'])
    if scorecard['status']!='pass':
        log.error('Failing contracts: %s %s',scorecard['factuality_contract']['failures'],
                  scorecard['routing_contract']['failures'])
        raise SystemExit(1)

if __name__=='__main__':
    main()
