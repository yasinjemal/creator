import os
import time
import json
import logging
from datetime import datetime

from redis import Redis
from rq import Queue


class JSONFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'ts': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'msg': record.getMessage(),
        }
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logger():
    logger = logging.getLogger('scheduler')
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(JSONFormatter())
    logger.addHandler(h)
    return logger


def main():
    logger = setup_logger()

    redis_host = os.getenv('REDIS_HOST', 'redis')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    interval = int(os.getenv('TEMP_CLEANUP_INTERVAL_SECONDS', '3600'))
    backoff_min = int(os.getenv('SCHEDULER_BACKOFF_MIN', '1'))
    backoff_max = int(os.getenv('SCHEDULER_BACKOFF_MAX', '300'))
    startup_timeout = int(os.getenv('SCHEDULER_STARTUP_TIMEOUT', '60'))
    startup_backoff_max = int(os.getenv('SCHEDULER_STARTUP_BACKOFF_MAX', '10'))

    logger.info(f"starting enqueuer", extra={'redis': f'{redis_host}:{redis_port}', 'interval': interval})

    # Establish Redis connection with startup retry/backoff
    start = time.time()
    attempt = 0
    startup_backoff = 1
    redis_conn = None
    while True:
        attempt += 1
        try:
            logger.info('attempting_redis_connect', extra={'attempt': attempt, 'host': redis_host, 'port': redis_port})
            redis_conn = Redis(host=redis_host, port=redis_port)
            # quick ping to verify connection
            redis_conn.ping()
            logger.info('redis_connected', extra={'attempt': attempt})
            break
        except Exception:
            elapsed = time.time() - start
            if elapsed > startup_timeout:
                logger.error('redis_connect_timeout', extra={'elapsed': elapsed}, exc_info=True)
                raise
            logger.info(f'redis_connect_backoff {startup_backoff}s')
            time.sleep(startup_backoff)
            startup_backoff = min(startup_backoff * 2, startup_backoff_max)

    q = Queue(connection=redis_conn)

    backoff = backoff_min
    try:
        while True:
            try:
                q.enqueue('worker_tasks.cleanup_temp_uploads')
                # update health marker
                try:
                    redis_conn.set('scheduler:last_success', int(time.time()))
                except Exception:
                    pass
                logger.info('enqueued cleanup_temp_uploads')
                backoff = backoff_min
            except Exception as e:
                logger.error('enqueue_failed', exc_info=True)
                logger.info(f'backing off for {backoff}s')
                time.sleep(backoff)
                backoff = min(backoff * 2, backoff_max)
                continue

            # sleep until next interval
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info('stopping scheduler')


if __name__ == '__main__':
    main()
