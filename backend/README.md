# Prompt Attack Annotation Platform — Backend

FastAPI + SQLAlchemy 2 + PostgreSQL backend for the Prompt Attack Annotation
Platform (Han Digital). It also serves the plain-HTML frontend from
`../frontend`, so the whole app runs same-origin on one port.

## Stack

- Python 3.12, FastAPI, Uvicorn
- SQLAlchemy 2 (PostgreSQL via psycopg2)
- Alembic migrations
- JWT access tokens + rotating httpOnly refresh cookie
- Passlib / bcrypt password hashing
- pytest + httpx (`tests/test_smoke_api.py`)

## Modules / API

| Feature key         | Router               | Purpose                                              |
| ------------------- | -------------------- | ---------------------------------------------------- |
| `dashboard`         | `/api/v1/dashboard`  | Stats, active queues, live activity                  |
| `projects`          | `/api/v1/projects`   | Projects that group queues                           |
| `queues`            | `/api/v1/queues`     | Queues, task lists, assignment                       |
| `tasks`             | `/api/v1/tasks`      | Task monitoring, Excel export, QA re-inject          |
| `roles`             | `/api/v1/roles`      | Roles and feature permissions                        |
| `users`             | `/api/v1/users`      | Users, import/export, activation                     |
| `annotation_queues` | `/api/v1/queues`     | Queues assigned to the current user                  |
| `profile`           | `/api/v1/auth`       | `me`, sessions, change-password, logout(-all)        |

Other routers: `/api/v1/auth` (login/refresh/logout), `/api/v1/features`,
`/api/v1/upload` (task files: images, documents, `.json/.jsonl/.md/.xlsx`, ...).

## Prerequisites

- PostgreSQL running on `127.0.0.1:5432` with user `postgres` / password `1234`
  (change via `.env`).
- Python 3.12 virtual environment at `backend/.venv` with `requirements.txt`
  installed.

```bat
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Database

The app database is **`annotation_tool_promptattack`**.

On startup the app connects to the maintenance database (`MAINTENANCE_DB`,
default `postgres`) and runs `CREATE DATABASE "annotation_tool_promptattack"`
if it does not exist, then creates all tables (`create_all`) and seeds the
default features, the `Administrator` role and the default admin user.

If you prefer to create it yourself (or the maintenance DB is not reachable):

```sql
CREATE DATABASE annotation_tool_promptattack;
```

### Alembic

The schema also ships as a single migration
(`alembic/versions/0001_initial_promptattack_schema.py`). To manage the schema
with Alembic instead of `create_all`:

```bat
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
```

`alembic.ini` points at
`postgresql://postgres:1234@127.0.0.1:5432/annotation_tool_promptattack`;
`alembic/env.py` reads the live URL from `app.core.config.settings`, so `.env`
wins when present. (A root-level `alembic.ini` with
`script_location = backend/alembic` exists for running from the repo root.)

## Run

```bat
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8005
```

Add `--reload` while developing. Port **8005** is the one the frontend, the
Docker healthcheck and the nginx proxy expect.

## Environment (`.env`)

Copy `.env.example` to `.env` and adjust:

```env
APP_NAME=Prompt Attack Annotation Platform API
API_V1_STR=/api/v1
SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_VALUE
ACCESS_TOKEN_EXPIRE_MINUTES=480
DB_USER=postgres
DB_PASS=1234
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=annotation_tool_promptattack
UPLOAD_FOLDER=uploads
FRONTEND_DIR=../frontend
CORS_ORIGINS=http://localhost:8005,http://127.0.0.1:8005,http://localhost:3000,http://127.0.0.1:3000
DEFAULT_ADMIN_EMAIL=admin@gmail.com
DEFAULT_ADMIN_PASSWORD=Admin@123
```

`FRONTEND_DIR` is resolved relative to the backend working directory; when the
folder exists it is mounted at `/` so the UI is served by FastAPI.

> The default admin password is re-applied on every startup by
> `seed_default_admin`, so a password changed via the UI reverts on restart
> unless `DEFAULT_ADMIN_PASSWORD` is updated too.

## Default admin

- Email: `admin@gmail.com` (`DEFAULT_ADMIN_EMAIL`)
- Password: `Admin@123` (`DEFAULT_ADMIN_PASSWORD`)

## Tests

The smoke test hits the real database configured in `.env` (it creates and
then deletes one project, one queue and two tasks):

```bat
cd backend
.venv\Scripts\python.exe -m pytest tests/test_smoke_api.py -q
```

## URLs

- App (login): [http://localhost:8005/](http://localhost:8005/)
- Swagger: [http://localhost:8005/docs](http://localhost:8005/docs)
- OpenAPI: [http://localhost:8005/api/v1/openapi.json](http://localhost:8005/api/v1/openapi.json)
- Health: [http://localhost:8005/health](http://localhost:8005/health)

## Docker

`Dockerfile` builds the API image (copies `app/`, `alembic/`, `alembic.ini`,
`scripts/`). The root `docker-compose.yml` starts Postgres, the backend (with
`alembic upgrade head` then uvicorn on 8005) and the nginx frontend on port 80.
