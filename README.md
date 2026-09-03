# Prompt Attack Annotation Platform

Han Digital's platform for organising, assigning and tracking prompt-attack
annotation work: projects, queues, tasks, roles, users, per-annotator queue
views and a profile/session page.

- **Backend**: FastAPI + SQLAlchemy 2 + PostgreSQL (`backend/`)
- **Frontend**: plain HTML + inline CSS + vanilla JS, no build step (`frontend/`)
- The backend serves the frontend same-origin, so a single process on port
  8005 runs the whole app.

## Structure

```
backend/
  app/            FastAPI application (api/v1, core, crud, models, schemas, services)
  alembic/        migrations (0001_initial_promptattack_schema)
  scripts/        init_db.py
  tests/          pytest smoke test against the real DB
  Dockerfile, entrypoint.sh, requirements.txt, .env(.example), README.md
frontend/
  index.html      login
  dashboard.html, projects.html, queues.html, queue-tasks.html, tasks.html,
  roles.html, users.html, annotation-queues.html, profile.html
  js/app.js       shared runtime (api client, session, shell, UI helpers, icons)
  public/         logos and favicon
  Dockerfile, nginx.conf
docker-compose.yml
alembic.ini       root alembic config (script_location = backend/alembic)
```

## Run locally

Requirements: PostgreSQL on `127.0.0.1:5432` (user `postgres`, password `1234`)
and a Python 3.12 venv in `backend/.venv` with `backend/requirements.txt`
installed. The database `annotation_tool_promptattack` is created
automatically on first start (or run `CREATE DATABASE annotation_tool_promptattack;`).

```bat
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8005
```

Open **http://localhost:8005/** and sign in with the default admin
(`admin@gmail.com` / `Admin@123`, configurable in `backend/.env`).

- Swagger: http://localhost:8005/docs
- Health: http://localhost:8005/health

See [backend/README.md](backend/README.md) for configuration, Alembic and tests.

## Docker Compose

```bash
docker compose up --build
```

Services: `db` (Postgres, `promptattack_db`), `backend` (`promptattack_backend`,
runs `alembic upgrade head` then uvicorn on 8005) and `frontend`
(`promptattack_frontend`, nginx on port 80 proxying `/api/` and `/health` to
the backend). Open http://localhost/ (or http://localhost:8005/ directly on
the backend).

A machine-specific, untracked `docker-compose.override.yml` can shift the
published ports (e.g. `8085:80`, `5435:5432`) when 80/5432 are already in use.

## Capacity and scaling

The tool is built to serve 200+ concurrent annotators over 10,000-task queues.
The design follows SageMaker Ground Truth: work is handed out as short
**leases**, every state change is re-checked under a row lock, and no request
ever downloads a whole queue.

- **Claims and leases.** `GET /workspace/queues/{id}/next` picks *and reserves*
  a task (`SELECT ... FOR UPDATE SKIP LOCKED`). The workspace heartbeats the
  lease every 60 s (`POST /workspace/tasks/{id}/heartbeat`); a claim idle for
  `CLAIM_LEASE_SECONDS` (default 600) stops blocking other annotators and an
  empty one is purged, so an abandoned browser tab never hides a task. QA tasks
  carry the same lease (`qa_owner_id` / `qa_owner_seen_at`).
- **Conflicts are explicit.** A write that loses a race (a task that already
  has its N responses, a QA task held by another reviewer, a task already
  finalised) returns **HTTP 409**; the workspace shows the message and asks for
  the next task. Surplus answers are never stored.
- **One open response per user per task** is enforced by a partial unique index
  (`uq_task_annotations_open`); the same annotator may still answer again once
  their first response is submitted, but a repeat never reserves a slot ahead of
  a distinct annotator.
- **Fixed statement budgets.** Claim, heartbeat, autosave, queue summary and the
  per-user queue list issue a small fixed number of statements regardless of
  queue size (`backend/tests/test_query_budget.py`). Measured on a 10,000-task
  queue: claim ~35 ms, summary ~35 ms, heartbeat ~2 ms, my-queues ~20 ms.
- **Processes, not threads.** The container runs gunicorn with uvicorn workers
  (`backend/gunicorn.conf.py`); `WEB_CONCURRENCY` (default 4) x
  (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) must stay below Postgres
  `max_connections` (compose: 4 x 20 = 80 against 200). Startup schema/seed
  work runs under a Postgres advisory lock so workers can boot together. The
  seed never rewrites passwords or deletes roles.
- **Exports stream.** JSON/JSONL are streamed page by page; XLSX is written in
  openpyxl write-only mode to a temp file. Memory stays flat for any queue size.
- **Edge caching.** nginx gzips text assets and caches versioned files
  (`js/app.js?v=...`) for a year; HTML is always revalidated. The icon table
  lives in `js/icons.js` so it caches independently of `app.js`.
- **Login protection.** 10 attempts per minute per client/email before hashing;
  dead sessions and old audit rows are trimmed opportunistically.

Tunables (env): `CLAIM_LEASE_SECONDS`, `REFRESH_GRACE_SECONDS`, `USER_CACHE_SECONDS`,
`DASHBOARD_CACHE_SECONDS`, `THREADPOOL_TOKENS`, `WEB_CONCURRENCY`, `DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `GUNICORN_TIMEOUT`.

## Tests

```bat
cd backend
.venv\Scripts\python.exe -m pytest tests/test_smoke_api.py -q
```
