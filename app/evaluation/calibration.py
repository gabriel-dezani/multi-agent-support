"""Calibration of a fallible semantic judge against human-reviewed labels."""


def calibration_metrics(items: list[dict]) -> dict:
    """Treat wrongly accepted unsupported answers as the primary safety defect.

    Each item contains human_supported (truth) and judge_supported (prediction).
    There is deliberately no 'accuracy' pass without negative examples.
    """
    if not items:
        raise ValueError('No evaluated labels')
    tp = tn = fp = fn = 0
    for item in items:
        human, judge = item['human_supported'], item['judge_supported']
        if not isinstance(human, bool) or not isinstance(judge, bool):
            raise ValueError('Labels must be booleans')
        if human and judge: tp += 1
        elif not human and not judge: tn += 1
        elif not human and judge: fp += 1
        else: fn += 1
    return {'samples':len(items), 'positive_examples':tp+fn,
            'negative_examples':tn+fp, 'true_positive':tp, 'true_negative':tn,
            'false_accepts':fp, 'false_rejects':fn,
            'false_accept_rate': round(fp/(fp+tn),4) if fp+tn else None,
            'precision': round(tp/(tp+fp),4) if tp+fp else None,
            'recall': round(tp/(tp+fn),4) if tp+fn else None}


def calibration_gate(metrics: dict, *, min_total: int = 20,
                     min_negative: int = 8, min_positive: int = 8,
                     max_false_accept_rate: float = .05,
                     min_supported_recall: float = .70) -> list[str]:
    """Reject always-negative, always-positive and biased synthetic judges.

    The false-accept gate protects against hallucinations; a positive recall
    gate prevents achieving it by simply rejecting every correct answer.
    Labels must actually be reviewed by humans for the result to be meaningful.
    """
    import math
    if any(type(n) is not int or n < 1 for n in (min_total,min_negative,min_positive)):
        raise ValueError('Minimum case counts must be positive integers')
    if any(not isinstance(n,(int,float)) or isinstance(n,bool) or not math.isfinite(n)
           or not 0 <= n <= 1 for n in (max_false_accept_rate,min_supported_recall)):
        raise ValueError('Rate thresholds must be finite in [0,1]')
    failures=[]
    if metrics['samples'] < min_total:
        failures.append('Insufficient human-reviewed cases')
    if metrics['negative_examples'] < min_negative:
        failures.append('Insufficient negative/hallucination cases')
    if metrics['positive_examples'] < min_positive:
        failures.append('Insufficient supported-answer cases')
    if metrics['false_accept_rate'] is None or metrics['false_accept_rate'] > max_false_accept_rate:
        failures.append('Judge falsely accepts too many unsupported answers')
    if metrics['recall'] is None or metrics['recall'] < min_supported_recall:
        failures.append('Judge rejects too many supported answers')
    return failures
