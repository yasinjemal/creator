import os
import time
from redis import Redis
from rq import Queue

# This script runs in the backend image and periodically enqueues a token rotation job.
# It expects Redis to be reachable via REDIS_HOST/REDIS_PORT and worker_tasks.rotate_tokens

redis_conn = Redis(host=os.getenv('REDIS_HOST', 'redis'), port=int(os.getenv('REDIS_PORT', 6379)))
q = Queue(connection=redis_conn)

INTERVAL = int(os.getenv('REFRESH_INTERVAL_SECONDS', '60'))

if __name__ == '__main__':
    print('Token refresher starting...')
    while True:
        try:
            job = q.enqueue('worker_tasks.rotate_tokens')
            print('Enqueued rotate_tokens job', job.get_id())
        except Exception as e:
            print('Failed to enqueue rotate_tokens', e)
        time.sleep(INTERVAL)
