"""Failing quality gate for the reviewer's regression matrix (offline)."""
import json
from pathlib import Path
from app.agents.router import RouterAgent
from app.orchestration.privacy import safe_public_search_query


def main():
    dataset = json.loads(Path('data/evaluation_feedback_v6.json').read_text(encoding='utf-8'))
    planner = RouterAgent(enable_llm=False)
    results = []
    for item in dataset:
        history = [entry for m in item.get('previous_users', [])
                   for entry in ({'role': 'user', 'content': m},
                                 {'role': 'assistant', 'content': '(resposta anterior)'})]
        actual = planner.route(item['message'], 'cliente1988', history=history)['plan']
        passed = actual == item['expected_plan']
        privacy = None
        if 'expected_public_query' in item:
            privacy = safe_public_search_query(item['message'])
            passed = passed and privacy == item['expected_public_query']
        results.append({'id': item['id'], 'passed': passed, 'expected': item['expected_plan'],
                        'actual': actual, 'public_query': privacy})
    report = {'cases': len(results), 'passed': sum(int(x['passed']) for x in results),
              'accuracy': sum(int(x['passed']) for x in results) / len(results), 'results': results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['passed'] != report['cases']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
