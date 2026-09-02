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

## Tests

```bat
cd backend
.venv\Scripts\python.exe -m pytest tests/test_smoke_api.py -q
```
