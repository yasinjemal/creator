import os
import subprocess
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


def _project_root():
    return Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.getenv('RUN_INTEGRATION_TESTS') != '1', reason='integration tests disabled')
def test_scheduler_writes_redis_marker():
    """Start redis + scheduler via docker-compose and assert scheduler:last_success appears."""

    try:
        import redis
    except Exception:
        pytest.skip('redis package not available')

    infra_dir = _project_root() / 'infra'

    # start services
    up = subprocess.run(['docker', 'compose', 'up', '-d', 'redis', 'scheduler'], cwd=str(infra_dir))
    if up.returncode != 0:
        pytest.skip('docker compose up failed or not available')

    r = redis.Redis(host='localhost', port=6379)

    deadline = time.time() + 120
    found = False
    try:
        while time.time() < deadline:
            try:
                v = r.get('scheduler:last_success')
                if v:
                    found = True
                    # sanity: value should parse as int
                    int(v)
                    break
            except Exception:
                pass
            time.sleep(1)
        assert found, 'scheduler:last_success not found in Redis'
    finally:
        # tear down
        subprocess.run(['docker', 'compose', 'down'], cwd=str(infra_dir))
