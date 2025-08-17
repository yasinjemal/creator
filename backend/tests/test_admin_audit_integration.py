import os
import time
import pytest
from pathlib import Path

try:
    # optional imports for integration test runtime
    import requests
    from pymongo import MongoClient
except Exception:
    requests = None
    MongoClient = None


# Opt-in integration test. Set RUN_INTEGRATION_TESTS=1 and ensure docker-compose services are running.
if os.getenv('RUN_INTEGRATION_TESTS', '0') != '1':
    pytest.skip('Integration tests disabled; set RUN_INTEGRATION_TESTS=1 to enable', allow_module_level=True)


def _load_env_from_repo_root():
    """Load .env from repo root if python-dotenv is available and env vars missing."""
    try:
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[2]
        envfile = root / '.env'
        if envfile.exists():
            load_dotenv(envfile)
    except Exception:
        pass


def test_admin_audit_roundtrip():
    # try to populate environment from repo .env if present
    _load_env_from_repo_root()

    assert requests is not None and MongoClient is not None, 'requests and pymongo must be installed to run this integration test'

    # When running inside the backend container the app listens on port 8000.
    # If running tests from host, set BACKEND_URL env to the host-mapped URL (e.g. http://localhost:18000).
    backend_url = os.getenv('BACKEND_URL', 'http://localhost:8000')
    admin_key = os.getenv('ADMIN_API_KEY')
    assert admin_key, 'ADMIN_API_KEY must be set (export or in .env) to run this integration test'

    # Call protected admin endpoint
    r = requests.get(f"{backend_url}/api/admin/oauth/health", headers={'X-Admin-Key': admin_key}, timeout=10)
    assert r.status_code == 200, f'admin endpoint returned {r.status_code}: {r.text}'

    # Poll Mongo for the persisted audit event with a short timeout to avoid flakiness
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017/creatorflow')
    client = MongoClient(mongo_uri)
    db = client.get_default_database()

    deadline = time.time() + 10.0
    doc = None
    while time.time() < deadline:
        doc = db.admin_audit.find_one(sort=[('ts', -1)])
        if doc and doc.get('path') == '/api/admin/oauth/health' and doc.get('action') == 'auth':
            break
        time.sleep(0.5)

    assert doc is not None, 'No admin_audit document found within timeout'
    assert doc.get('path') == '/api/admin/oauth/health'
    assert doc.get('action') == 'auth'
    assert 'admin_key_masked' in doc
    # basic mask format check: starts with first 4 chars followed by '...' or contains '...'
    admin_key_masked = doc.get('admin_key_masked')
    assert isinstance(admin_key_masked, str) and '...' in admin_key_masked
