# PostgreSQL contract timeout investigation

The supplied workspace has no `.git` directory and no PostgreSQL, Docker,
`psql`, or psycopg installation. The PR run and its precise last operation
cannot be reconstructed here. No remote changes or paid APIs are needed.

## Findings and changes

- The termination test called `release.set()` in `finally` after terminating
  the child waiting on that multiprocessing Event. Termination can orphan its
  internal condition mutex, hanging the parent in `set()` indefinitely. The
  existing five-second joins do not bound that call. Cleanup now avoids the
  Event entirely after termination and bounds reaping with terminate/kill.
  Offline regression models an orphaned Event and covers both child exits.
  An isolated offline reproduction using real spawned processes also hung in
  the original `release.set()` after the child had been reaped; an external
  six-second timeout killed the reproducer. This confirms the defect, though
  the precise stopping point of the historical Actions run remains unproven.
- Request advisory locks and memory transaction locks already have different
  namespaces. No self-deadlock between those two keys was found. Existing real
  tests still verify nested writes, mutual exclusion, different keys, timeout,
  normal child exit, and lock recovery after child termination. The child uses
  autocommit so waiting on a session lock does not leave an idle transaction.
  Connections remain scoped to context managers; no shared pool or retry of
  mutations was introduced.
- Every append probes idempotency by conversation, user, and request ID.
  Previously only the conversation/user/id index existed, allowing repeated
  scans of the growing conversation. An additive request index now supports
  that probe. All 1,000 appends still open independent transactions and commit;
  writes were not batched and durability settings were not relaxed.
- Migrations run on construction, not each append. Reconstructing the store at
  250/500/1,000 turns intentionally verifies restart/recovery. Those migrations
  and reads have separate timers; they have not been cached or removed.
- Coverage still measures the parent and multiprocessing children. Forced
  child termination can lose that child's coverage; the normal-exit child and
  parent still contribute. No claim about coverage overhead is possible without
  real database timings. Stage times are recorded under coverage; the same
  smoke can be run without coverage against the same disposable service for
  comparison (new sessions are generated on every invocation).
- Each stage logs start, completion/failure and elapsed seconds; the long test
  logs progress every 100 writes. Every 60 seconds faulthandler dumps all parent
  thread stacks, including blocked thread-pool operations. SIGTERM logs stacks
  and exits normally enough for coverage to save the parent's partial data.
  Diagnostics omit DSNs and SQL payloads.
- The job now allows 20 minutes, with a separate 15-minute smoke deadline and
  a 20-second forced-kill grace. The reserve is for installation, diagnostics,
  coverage combination and artifact upload. This supplements the Event fix.
  Service logs and lock/activity snapshots run with `always()`. Coverage is
  generated separately with `always()` and uploaded with logs and raw coverage.
  A failed smoke remains a failed job even if partial coverage is generated.
  Abrupt runner termination/manual cancellation cannot guarantee artifact upload;
  live logs and periodic stacks remain the fallback.

## Validation commands

Local results: full offline suite **418 passed**, no skips (173.78 seconds);
targeted persistence/lock suite **62 passed**; graph smoke **24 checks passed**;
long-turn scorecard **134 checks passed**, zero API calls. Compileall and YAML
parsing passed. Existing dependency deprecation/relevance warnings remain.

Offline, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
```

Against a disposable PostgreSQL 16 service, set `TEST_POSTGRES_DSN` in the
process environment (do not edit `.env`). Install `requirements-postgres.txt`
in the validation environment. The Actions job runs:

```sh
python -u -m coverage run --rcfile=.coveragerc.postgres -m scripts.postgres_state_smoke
python -m coverage combine --rcfile=.coveragerc.postgres
python -m coverage json --rcfile=.coveragerc.postgres -o postgres-coverage.json
python -m coverage report --rcfile=.coveragerc.postgres -m
```

For an overhead comparison, run `python -u -m scripts.postgres_state_smoke`
against the same disposable service and compare total and stage durations.
This is optional and does not replace the instrumented covered CI contract.

Real PostgreSQL atomicity, rollback, isolation, competing connections/processes,
release after termination, 250/500/1,000-turn restart recovery, index performance,
and coverage generation still require the PostgreSQL Actions job (or an
equivalent local disposable PostgreSQL 16 environment). Offline tests do not
establish those database guarantees or the original run's exact blocking site.
