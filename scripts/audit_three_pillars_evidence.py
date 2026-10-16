"""Synthetic before/after policy evidence, never a human semantic evaluation."""
import json
from pathlib import Path
from types import FunctionType

from app.orchestration.review_policy import choose_next, _weak_result
from app.evaluation.retrieval import metrics_at_k


def legacy_unresolved(state):
    """Frozen recovery predicate from the local V8.3 before this audit."""
    results = state.get('agent_results', [])
    web = bool(state.get('web_getnet_only') and any(
        r.get('agent') == 'web_search' and not r.get('requires_human') and r.get('sources') for r in results))
    rag = bool(state.get('rag_getnet_recovery') and any(
        r.get('agent') == 'knowledge' and not r.get('requires_human') and r.get('sources') for r in results))
    return [str(r.get('agent','unknown')) for r in results
            if not r.get('provider_unavailable') and _weak_result(r) and not (
                (web and r.get('agent') == 'knowledge') or (rag and r.get('agent') == 'web_search'))]


def evaluate():
    baseline = FunctionType(choose_next.__code__, {**choose_next.__globals__, 'unresolved':legacy_unresolved})
    cases = []
    for recovery, flag in [('web_search','web_getnet_only'),('knowledge','rag_getnet_recovery')]:
        failed = 'knowledge' if recovery == 'web_search' else 'web_search'
        # An outage used to hide the weak recovery result itself, allowing an
        # empty synthesis after the failed first specialist was marked resolved.
        for label, change, expected in [
            ('empty_outage',dict(answer='',provider_unavailable=True),'human_escalation'),
            ('weak_outage',dict(confidence=.1,provider_unavailable=True),'human_escalation'),
            ('valid',{},'synthesis'),
        ]:
            result = dict(agent=recovery,answer='Supported answer',confidence=.9,
                          requires_human=False,sources=['https://site.getnet.com.br/pix/'])
            result.update(change)
            state = dict(plan=[failed,recovery],current_step=2,agent_results=[
                dict(agent=failed,answer='',sources=[],confidence=0,requires_human=True), result])
            state[flag] = True
            cases.append(dict(id=recovery+'/'+label,expected=expected,
                              before=baseline(state),after=choose_next(state)))
    url = 'https://site.getnet.com.br/Product?version=2'
    metrics = metrics_at_k([url], ['http://invalid.example', url, url], 3)
    return dict(scope='synthetic_developer_regressions_only',human_reviewed=False,external_api_calls=0,
                supervisor=dict(cases=len(cases),before_correct=sum(c['before']==c['expected'] for c in cases),
                                after_correct=sum(c['after']==c['expected'] for c in cases),details=cases),
                retrieval_metric_fixture=metrics,
                limitation='Frozen pre-audit recovery predicate; no claim of real-world accuracy or retrieval gain')


if __name__ == '__main__':
    report = evaluate()
    Path('docs/audit_three_pillars_decisions.json').write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    assert report['supervisor']['after_correct'] == report['supervisor']['cases']
