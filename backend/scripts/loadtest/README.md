# Load-test harness

Drives the real API with hundreds of virtual annotators, reviewers and admins,
then verifies the data invariants. Everything it creates is tagged
(`LT-*` queues, `*@lt.flowtest.dev` users) and removed by `cleanup`.

```bash
# from backend/ (venv active), API running on http://127.0.0.1:8011
python -m scripts.loadtest.seed --annotators 200 --reviewers 30 --queues 20 --tasks 500
python -m scripts.loadtest.run  --annotators 100 --reviewers 15 --admins 1 --offset 0   --rev-offset 0  --duration 90 --think 10 &
python -m scripts.loadtest.run  --annotators 100 --reviewers 15 --admins 1 --offset 100 --rev-offset 15 --duration 90 --think 10 &
wait
python -m scripts.loadtest.check      # every invariant must print 0 rows
python -m scripts.loadtest.cleanup
```

Run the target with several worker processes, e.g. locally
`uvicorn app.main:app --workers 4 --port 8011 --timeout-keep-alive 75`
(the `backend-load` entry in `.claude/launch.json`) or the compose stack.
Shard the generator across processes with `--offset/--rev-offset`; one
process drives ~120 virtual users. `--think` is the pause between steps:
real annotators need minutes per task, so `--think 10` (one task per ~40 s
per annotator) is already faster than reality and `--think 2` is a stress
test.

## Reference results (2026-09-03)

Windows laptop, 8 cores shared by 4 uvicorn workers, local PostgreSQL 18,
and both generator processes. 20 queues x 500 tasks (10,000), 200
annotators + 30 reviewers + 2 admins, 90 s at full load after a 20 s ramp.

Realistic pace (`--think 10`, ~45 req/s):

| Operation | p50 | p95 | p99 |
|---|---|---|---|
| open task | 16 ms | 58 ms | 138 ms |
| autosave (draft) | 38 ms | 105 ms | 195 ms |
| heartbeat | 34 ms | 108 ms | 262 ms |
| submit | 113 ms | 187 ms | 265 ms |
| claim next task | 70 ms | 163 ms | 322 ms |
| my queues list | 153 ms | 290 ms | 302 ms |
| QA finalize | 77 ms | 158 ms | 225 ms |
| login (232 in 20 s) | 71 ms | 127 ms | 229 ms |

Errors 0, conflicts 0, 821 tasks submitted and 185 finalised in the window,
XLSX export of a 500-task queue 2.5 s, all integrity checks 0 rows.

Stress pace (`--think 2`, ~97 req/s offered): the laptop saturates at about
100-110 req/s (API workers at ~3.4 cores) and latency turns into admission
queueing (p50 ~1 s, no errors, integrity still clean). A dedicated Linux host
with Postgres on its own machine is expected to sustain several times that;
re-run this harness there to confirm before go-live.

## Invariants checked (`check.py`)

- no task has more submitted responses than its queue requires
- one open response per user per task
- `submitted_count` matches the submitted rows
- a task awaiting review has a QA queue; an approved task has a final record
  and stays attached to QA; a returned task is detached and has none
- no approved/returned task still holds a QA owner lease
- exactly one QA queue per production queue
- every `tasks_output` row points at an existing response
