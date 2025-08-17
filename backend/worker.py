from rq import Connection, Worker
from redis import Redis
import os
import threading
import time

redis_conn = Redis(host=os.getenv('REDIS_HOST', 'redis'), port=int(os.getenv('REDIS_PORT', 6379)))


def _start_periodic_cleanup(interval_seconds: int = 3600):
    """Start a background thread that enqueues cleanup_temp_uploads every interval_seconds.

    This avoids an external scheduler dependency; the thread enqueues a job on the
    default RQ queue which will be executed by the worker as a normal job.
    """
    from rq import Queue

    def _loop():
        q = Queue(connection=redis_conn)
        while True:
            try:
                q.enqueue('worker_tasks.cleanup_temp_uploads')
            except Exception:
                # swallow errors to keep scheduler alive
                pass
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


if __name__ == '__main__':
    # read interval from env (seconds); default to 3600 (1 hour)
    try:
        interval = int(os.getenv('TEMP_CLEANUP_INTERVAL_SECONDS', '3600'))
    except Exception:
        interval = 3600

    # Start periodic cleanup enqueuer only when explicitly enabled (so we can run a single scheduler container)
    if os.getenv('ENABLE_PERIODIC_CLEANUP_ENQUEUER', '0') in ('1', 'true', 'True'):
        _start_periodic_cleanup(interval_seconds=interval)

    with Connection(redis_conn):
        worker = Worker(['default'])
        worker.work()
