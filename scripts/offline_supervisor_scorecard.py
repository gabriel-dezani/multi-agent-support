"""Developer-labeled, deterministic supervisor decision regression benchmark.

No LLM/API calls. This does NOT measure real LLM autonomy, factuality or live
retrieval; it verifies that planned transitions obey security and budget rules.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path

from app.orchestration.review_policy import bounded_replan, choose_next

log = logging.getLogger(__name__)


def evaluate_cases(cases: list[dict]) -> dict:
    if not isinstance(cases, list) or len(cases) < 15:
        raise ValueError('At least 15 developer-labeled cases required')
    seen = set()
    failures = []
    for case in cases:
        case_id = case['id']
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError('Duplicate or invalid test case ID')
        seen.add(case_id)
        state = {key:case[key] for key in ('message','plan','current_step','agent_results')}
        changed = bounded_replan(state, web_available=case['web_available'],
                                 max_agents=case['max_agents'])
        node = choose_next({**state, **changed})
        # Expect precise change, not just a passed boolean. The benchmark also
        # catches private-data escalation into public search.
        if changed != case['expected_replan'] or node != case['expected_next']:
            failures.append({'id':case_id,'expected_next':case['expected_next'],
                             'actual_next':node, 'expected_replan':case['expected_replan'],
                             'actual_replan':changed})
    return {'status':'pass' if not failures else 'fail',
            'scope':'developer-labeled_deterministic_supervisor_only',
            'external_api_calls':0, 'cases':len(cases), 'failures':failures,
            'human_reviewed':False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',default='data/supervisor_policy_regressions.json')
    parser.add_argument('--output',default='supervisor_scorecard.json')
    args=parser.parse_args()
    raw=Path(args.dataset).read_bytes()
    report=evaluate_cases(json.loads(raw))
    report['dataset_sha256']=hashlib.sha256(raw).hexdigest()
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    log.info('Offline supervisor policy: %s (%d synthetic cases; API calls: 0)',
             report['status'],report['cases'])
    if report['failures']:
        for failure in report['failures']:
            log.error('Supervisor regression %s: expected %s, actual %s',
                      failure['id'],failure['expected_next'],failure['actual_next'])
        raise SystemExit(1)


if __name__=='__main__':
    main()
