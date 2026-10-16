"""Local, read-only operational release review of recorded request statistics.

No external services are contacted. A local healthy verdict is not proof of
multi-replica readiness, OIDC deployment or semantic LLM quality.
"""
import argparse
import json
import logging
from pathlib import Path

from app.core.telemetry import TelemetryRepository
from app.core.observability import evaluate_slo, evaluate_operational_gates

log = logging.getLogger(__name__)


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--db', default='.state/support.db', help='Local SQLite telemetry DB')
    cli.add_argument('--minutes', type=int, default=60, help='UTC rolling window: 5..1440')
    cli.add_argument('--output', default='operational_review.json')
    args = cli.parse_args()
    path = Path(args.db)
    if not path.is_file():
        cli.error('Telemetry DB does not exist. Do not create a synthetic PASS.')
    # Ensure this command does not migrate or mutate a production DB; the
    # repository's constructor performs schema initialization, so use a
    # temporary read-only instance for this reporting operation.
    repository = TelemetryRepository.__new__(TelemetryRepository)
    repository.path = path
    try:
        stats = repository.recent_stats(window_minutes=args.minutes)
    except Exception as exc:
        # Do not include exception messages that may contain local paths.
        log.error('Operational telemetry report failed: %s', type(exc).__name__)
        raise SystemExit(2) from exc
    report = {
        'scope':'local_utc_rolling_window',
        'stats':stats,
        'slo':evaluate_slo(stats),
        'operational_alerts':evaluate_operational_gates(stats),
        'limitations':["does not check distributed deployment", "does not evaluate LLM answer quality",
                       "alerts are evaluated on demand; external alert delivery requires integration"],
        'external_api_calls':0,
    }
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    log.info('Local SLO: %s; operational gates: %s; %d requests in window',
             report['slo']['status'],report['operational_alerts']['status'],stats['requests'])
    # Unknown/insufficient data is not interpreted as passing the gate.
    if report['slo']['status']!='pass' or report['operational_alerts']['status']!='healthy':
        raise SystemExit(1)


if __name__=='__main__':
    main()
