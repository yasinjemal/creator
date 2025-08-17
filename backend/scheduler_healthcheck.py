import os
import sys
import time

from redis import Redis


def main():
    redis_host = os.getenv('REDIS_HOST', 'redis')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    ttl_seconds = int(os.getenv('SCHEDULER_HEALTH_TTL', 1200))

    r = Redis(host=redis_host, port=redis_port)
    try:
        v = r.get('scheduler:last_success')
        if not v:
            print('no marker')
            sys.exit(1)
        last = int(v)
        if time.time() - last > ttl_seconds:
            print('stale')
            sys.exit(1)
        print('ok')
        sys.exit(0)
    except Exception as e:
        print('error', e)
        sys.exit(1)


if __name__ == '__main__':
    main()
