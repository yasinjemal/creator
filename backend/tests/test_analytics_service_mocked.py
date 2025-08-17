import pytest
from unittest import mock

try:
    # when running tests from repo root (PYTHONPATH=/repo)
    from backend.services import analytics_service as svc
except Exception:
    # when running inside the backend container where /app contains the backend package contents
    from services import analytics_service as svc


class DummyToken(dict):
    pass


def make_response(json_data, status_code=200):
    class Resp:
        def __init__(self, j, status):
            self._j = j
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"HTTP {self.status_code}")

        def json(self):
            return self._j

        @property
        def headers(self):
            return {}

    return Resp(json_data, status_code)


def test_fetch_channel_kpis_live_path_parses_rows(monkeypatch):
    # Mock token retrieval
    dummy_token = DummyToken(access_token='FAKE')

    class FakeAdapter:
        def __init__(self, cfg=None):
            pass

        def get_token(self, brand_id, platform):
            return dummy_token

        def refresh_access_token(self, brand_id, platform):
            return None

    monkeypatch.setattr(svc, 'YouTubeAdapter', FakeAdapter)

    # Mock requests.get for analytics reports
    analytics_payload = {'rows': [["2025-08-01", 1234, 56.7, 10]]}
    def fake_get(url, params=None, headers=None, timeout=None):
        if 'youtubeanalytics' in url:
            return make_response({'rows': [[1234, 56.7, 10]]}, 200)
        raise RuntimeError('unexpected url')

    monkeypatch.setattr(svc, 'requests', mock.MagicMock(get=fake_get))

    res = svc.fetch_channel_kpis('brand_live', window_days=7)
    assert res.get('views') == 1234
    assert res.get('watch_time') == int(56.7 * 60)
    assert res.get('subs_delta') == 10
    assert res.get('live') is True


def test_fetch_channel_kpis_api_error_falls_back(monkeypatch):
    # Adapter returns token but requests raises
    class FakeAdapter2:
        def __init__(self, cfg=None):
            pass

        def get_token(self, brand_id, platform):
            return DummyToken(access_token='FAKE')

        def refresh_access_token(self, brand_id, platform):
            return None

    monkeypatch.setattr(svc, 'YouTubeAdapter', FakeAdapter2)

    def bad_get(url, params=None, headers=None, timeout=None):
        raise Exception('network')

    monkeypatch.setattr(svc, 'requests', mock.MagicMock(get=bad_get))

    res = svc.fetch_channel_kpis('brand_err', window_days=7)
    assert 'live_error' in res
    assert 'views' in res and 'watch_time' in res


def test_fetch_top_videos_live_flow(monkeypatch):
    # Adapter token
    class FakeAdapter3:
        def __init__(self, cfg=None):
            pass

        def get_token(self, brand_id, platform):
            return DummyToken(access_token='FAKE')

        def refresh_access_token(self, brand_id, platform):
            return None

    monkeypatch.setattr(svc, 'YouTubeAdapter', FakeAdapter3)

    # First call returns rows of video ids; second call returns video details
    def fake_get(url, params=None, headers=None, timeout=None):
        if 'youtubeanalytics' in url:
            return make_response({'rows': [["vid1", 100], ["vid2", 50]]}, 200)
        if 'youtube/v3/videos' in url:
            return make_response({'items': [
                {'id': 'vid1', 'snippet': {'title': 'Video One'}, 'statistics': {'viewCount': '100'}},
                {'id': 'vid2', 'snippet': {'title': 'Video Two'}, 'statistics': {'viewCount': '50'}},
            ]}, 200)
        raise RuntimeError('unexpected url')

    monkeypatch.setattr(svc, 'requests', mock.MagicMock(get=fake_get))

    items = svc.fetch_top_videos('brand_v', limit=2)
    assert len(items) == 2
    assert items[0]['video_id'] == 'vid1'
    assert items[0]['title'] == 'Video One'


def test_build_timeseries_live_parsing(monkeypatch):
    class FakeAdapter4:
        def __init__(self, cfg=None):
            pass

        def get_token(self, brand_id, platform):
            return DummyToken(access_token='FAKE')

        def refresh_access_token(self, brand_id, platform):
            return None

    monkeypatch.setattr(svc, 'YouTubeAdapter', FakeAdapter4)

    def fake_get(url, params=None, headers=None, timeout=None):
        # return two days of data
        return make_response({'rows': [["2025-08-16", 10, 1.5, 1], ["2025-08-17", 20, 2.0, 2]]}, 200)

    monkeypatch.setattr(svc, 'requests', mock.MagicMock(get=fake_get))

    series = svc.build_timeseries('brand_ts', days=2)
    assert len(series) == 2
    assert series[0]['date'] == '2025-08-16'
    assert series[0]['views'] == 10
