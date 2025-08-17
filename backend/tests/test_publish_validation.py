import io
import importlib
import os

import pytest

# skip the whole module when Flask is not installed in the test environment
pytest.importorskip('flask')


class FakeDB:
    def __init__(self):
        self._drafts = {}

    def find_one(self, q):
        return self._drafts.get(q.get('_id'))

    def update_one(self, *a, **k):
        return None


class DummyJob:
    def __init__(self, id_='job1'):
        self._id = id_
    def get_id(self):
        return self._id


class DummyQueue:
    def enqueue(self, *a, **k):
        return DummyJob('jid')


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    # ensure deterministic defaults
    monkeypatch.setenv('MAX_UPLOAD_MB', '1')
    # import app module
    appmod = importlib.import_module('backend.app')
    monkeypatch.setattr(appmod, 'db', FakeDB())
    monkeypatch.setattr(appmod, 'q', DummyQueue())
    # ensure YouTube adapter publish returns pending_upload for tests
    try:
        yta = importlib.import_module('adapters.youtube_adapter')
        monkeypatch.setattr(yta.YouTubeAdapter, 'publish', lambda self, draft: {'status': 'pending_upload', 'upload_url': 'https://example.com/upload'})
    except Exception:
        # if adapter not available, ignore
        pass
    yield


def make_client():
    appmod = importlib.import_module('backend.app')
    return appmod.app.test_client(), appmod


def test_payload_too_large(monkeypatch):
    client, appmod = make_client()
    # set MAX_UPLOAD_MB small via env so 2MB file fails
    monkeypatch.setenv('MAX_UPLOAD_MB', '1')

    draft_id = 'd_large'
    appmod.db._drafts[draft_id] = {'_id': draft_id, 'platform': 'youtube', 'payload': {'snippet': {'title': 'T'}}}

    big = io.BytesIO(b'x' * (2 * 1024 * 1024))
    data = {
        'draft_id': draft_id,
        'file': (big, 'video.mp4')
    }
    resp = client.post('/api/content/publish', data=data, content_type='multipart/form-data')
    assert resp.status_code == 413
    j = resp.get_json()
    assert j.get('ok') is False
    assert j.get('code') == 'payload_too_large'


def test_unsupported_media_type(monkeypatch):
    client, appmod = make_client()
    monkeypatch.setenv('MAX_UPLOAD_MB', '10')

    draft_id = 'd_badtype'
    appmod.db._drafts[draft_id] = {'_id': draft_id, 'platform': 'youtube', 'payload': {'snippet': {'title': 'T'}}}

    small = io.BytesIO(b'abc')
    data = {'draft_id': draft_id, 'file': (small, 'virus.exe')}
    resp = client.post('/api/content/publish', data=data, content_type='multipart/form-data')
    assert resp.status_code == 415
    j = resp.get_json()
    assert j.get('ok') is False
    assert j.get('code') == 'unsupported_media_type'


def test_invalid_metadata(monkeypatch):
    client, appmod = make_client()
    monkeypatch.setenv('MAX_UPLOAD_MB', '10')

    draft_id = 'd_nometa'
    # missing snippet.title
    appmod.db._drafts[draft_id] = {'_id': draft_id, 'platform': 'youtube', 'payload': {}}

    small = io.BytesIO(b'abc')
    data = {'draft_id': draft_id, 'file': (small, 'video.mp4')}
    resp = client.post('/api/content/publish', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    j = resp.get_json()
    assert j.get('ok') is False
    assert j.get('code') == 'invalid_metadata'
