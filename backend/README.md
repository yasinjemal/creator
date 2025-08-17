# Backend (Flask)

Run locally:

python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; python app.py

The API exposes `/health` and `/api/brand` CRUD endpoints as a starting point.

Scheduler
---------

This project includes `backend/scheduler.py`, a small enqueuer that periodically enqueues `worker_tasks.cleanup_temp_uploads`.

It also includes `backend/scheduler_healthcheck.py` which inspects the Redis key `scheduler:last_success` (set by the scheduler) and exits with status 0 when the scheduler is healthy. Environment variables:

- `TEMP_CLEANUP_INTERVAL_SECONDS` — how often the scheduler enqueues the cleanup job (seconds).
- `SCHEDULER_HEALTH_TTL` — number of seconds before the last-success marker is considered stale by the healthcheck.

The `infra/docker-compose.yml` healthcheck for the `scheduler` service runs this script so Docker can detect scheduler failures.
