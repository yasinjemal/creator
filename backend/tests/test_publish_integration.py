import os
import time
import pytest
from pathlib import Path

try:
    import requests
    from pymongo import MongoClient
except Exception:
    requests = None
    MongoClient = None


# Opt-in integration test. Set RUN_INTEGRATION_TESTS=1 and ensure docker-compose services are running.
if os.getenv('RUN_INTEGRATION_TESTS', '0') != '1':
    pytest.skip('Integration tests disabled; set RUN_INTEGRATION_TESTS=1 to enable', allow_module_level=True)


def _load_env_from_repo_root():
    try:
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[2]
        envfile = root / '.env'
        if envfile.exists():
            load_dotenv(envfile)
    except Exception:
        pass


def test_publish_enqueues_and_worker_updates_draft():
    _load_env_from_repo_root()
    assert requests is not None and MongoClient is not None, 'requests and pymongo must be installed to run this integration test'

    backend_url = os.getenv('BACKEND_URL', 'http://localhost:8000')

    # create a brand
    r = requests.post(f"{backend_url}/api/brand", json={'name': 'PublishTest'})
    assert r.status_code in (200, 201), f'brand creation failed: {r.status_code} {r.text}'
    brand = r.json()
    brand_id = brand.get('_id')

    # generate a draft
    r = requests.post(f"{backend_url}/api/content/generate", json={'brand_id': brand_id, 'platform': 'youtube'})
    assert r.status_code == 200
    draft = r.json()
    draft_id = draft.get('_id')

    # call publish endpoint (no file) to exercise enqueue path / adapter stub
    r = requests.post(f"{backend_url}/api/content/publish", data={'draft_id': draft_id})
    assert r.status_code in (200, 202), f'publish endpoint failed: {r.status_code} {r.text}'

    # Poll Mongo for the draft to have status 'published' or 'error' updated by worker
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017/creatorflow')
    client = MongoClient(mongo_uri)
    db = client.get_default_database()

    deadline = time.time() + 20.0
    doc = None
    while time.time() < deadline:
        doc = db.drafts.find_one({'_id': draft_id})
        if doc and doc.get('status') in ('published', 'error'):
            break
        time.sleep(0.5)

    assert doc is not None, 'Draft was not updated by worker within timeout'
    assert doc.get('status') in ('published', 'error')
