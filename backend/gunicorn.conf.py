"""Gunicorn configuration: several uvicorn worker PROCESSES per container.

One process = one Python interpreter = one GIL. Serving 200+ annotators needs
several of them; each worker runs the FastAPI app with its own thread pool
and DB connection pool. Keep

    WEB_CONCURRENCY x (DB_POOL_SIZE + DB_MAX_OVERFLOW) < Postgres max_connections

(compose ships 4 x (10 + 10) = 80 against max_connections=200).
"""

import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY") or min(8, multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn_worker.UvicornWorker"
# Long enough for a 10,000-row import; exports stream so they never hit this.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
# Longer than the pauses between an annotator's requests (autosave debounce,
# heartbeat every 60 s) so the browser's keep-alive connection is reused
# instead of being torn down and re-opened for every request.
keepalive = 75
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
# Each worker runs the app lifespan itself (schema/seed under the startup
# advisory lock), so the app must NOT be preloaded in the master.
preload_app = False
# Recycle workers occasionally to bound any slow memory growth.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "5000"))
max_requests_jitter = 500
