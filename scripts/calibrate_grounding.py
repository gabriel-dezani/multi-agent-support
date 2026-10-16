"""Run live structured-LLM groundedness calibration against human labels.

No external services called without explicit OPENAI_API_KEY and dataset path.
The report is a model-dependent measurement, NOT proof of factual correctness.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
from app.evaluation.calibration import calibration_metrics, calibration_gate
from app.orchestration.privacy import contains_private_context


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('--dataset',required=True,
                     help='Human-reviewed JSON [{id,question,answer,evidence,human_supported,reviewed_by}]')
    cli.add_argument('--output',default='calibration_report.json')
    cli.add_argument('--min-cases',type=int,default=20)
    cli.add_argument('--min-negatives',type=int,default=8)
    cli.add_argument('--min-positives',type=int,default=8)
    cli.add_argument('--min-supported-recall',type=float,default=.70)
    cli.add_argument('--max-false-accept',type=float,default=.05)
    args=cli.parse_args()
    from app.core.config import get_settings
    settings=get_settings()
    if not settings.openai_api_key:
        cli.error('OPENAI_API_KEY is mandatory for real semantic calibration')
    content=Path(args.dataset).read_bytes()
    dataset=json.loads(content)
    if not isinstance(dataset,list):
        cli.error('Dataset must be a JSON list')
    seen=set()
    for item in dataset:
        if not isinstance(item,dict) or not isinstance(item.get('human_supported'),bool) or not item.get('reviewed_by'):
            cli.error('Every case must have explicit human_supported and reviewed_by')
        if not item.get('id') or item['id'] in seen:
            cli.error('Case IDs must be unique')
        seen.add(item['id'])
        if not isinstance(item.get('evidence'),list) or not all(isinstance(v,str) for v in item['evidence']):
            cli.error('Evidence must be an array of strings')
        if any(contains_private_context(text) for text in [item['question'],item['answer'],*item['evidence']]):
            cli.error('Private customer data detected: must not send dataset to a judge model')
    from langchain_openai import ChatOpenAI
    from app.rag.verification import second_pass_verify
    model=ChatOpenAI(model=settings.llm_model,api_key=settings.openai_api_key,
                     temperature=0,timeout=settings.request_timeout_seconds,max_retries=1)
    judgments=[]
    for item in dataset:
        accepted=second_pass_verify(llm=model,question=item['question'],
             answer=item['answer'],evidence=item['evidence'],
             minimum_score=settings.rag_verifier_min_score)
        judgments.append({'id':item['id'],'human_supported':item['human_supported'],
                          'judge_supported':accepted})
    scores=calibration_metrics(judgments)
    errors=calibration_gate(scores,min_total=args.min_cases,
          min_negative=args.min_negatives,min_positive=args.min_positives,
          min_supported_recall=args.min_supported_recall,
          max_false_accept_rate=args.max_false_accept)
    report={'model':settings.llm_model,'dataset_sha256':hashlib.sha256(content).hexdigest(),
            'human_calibrated':True, 'scores':scores,'violations':errors,
            'notes':'Live LLM judge is fallible; validate labels and retry across model releases.',
            'judgments':judgments}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("%s", json.dumps({'scores':scores,'violations':errors},ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__=='__main__':
    main()
