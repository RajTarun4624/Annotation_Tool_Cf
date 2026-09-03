FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (psycopg2-binary ships wheels, but build-essential covers edge cases)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (build context is the backend/ directory)
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts
COPY gunicorn.conf.py ./gunicorn.conf.py

EXPOSE 8000

# Several uvicorn worker processes (see gunicorn.conf.py). PORT and
# WEB_CONCURRENCY are environment-tunable.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
