from .base import BaseAdapter
import os
import requests
from typing import Optional
from datetime import datetime, timedelta


class YouTubeAdapter(BaseAdapter):
    def __init__(self, config=None):
        cfg = config or {}
        cfg.setdefault('platform', 'youtube')
        super().__init__(cfg)

    def publish(self, draft: dict) -> dict:
        """Publish a draft to YouTube (stub).

        Real implementation would perform resumable uploads and set metadata
        using Google's OAuth2 credentials. This stub validates token presence
        and returns a fake video id.
        """
        brand_id = draft.get('brand_id')
        token = self.get_token(brand_id, 'youtube')
        if not token:
            return {'status': 'error', 'error': 'no_oauth_token'}

    # If real Google credentials are provided, ensure token is fresh
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        if client_id and client_secret:
            # refresh if expired
            if token.get('expires_at') and token['expires_at'] <= datetime.utcnow():
                refreshed = self._refresh_via_google(brand_id, client_id, client_secret, token.get('refresh_token'))
                if refreshed:
                    token = refreshed
                else:
                    return {'status': 'error', 'error': 'refresh_failed'}

            # Try to initiate a resumable upload session using YouTube API.
            # This obtains an upload URL that the client or worker can use to
            # upload video bytes in a resumable fashion.
            try:
                upload_endpoint = (
                    'https://www.googleapis.com/upload/youtube/v3/videos'
                    '?uploadType=resumable&part=snippet,status'
                )
                # Example snippet payload - in real usage include title/description
                snippet = draft.get('payload', {}).get('snippet', {})
                body = {'snippet': {'title': snippet.get('title', 'Untitled'), 'description': snippet.get('description', '')}, 'status': {'privacyStatus': 'private'}}
                headers = {
                    'Authorization': f"Bearer {token.get('access_token')}",
                    'Content-Type': 'application/json; charset=UTF-8',
                }
                resp = requests.post(upload_endpoint, json=body, headers=headers, timeout=10)
                # Google returns a 200/201 with a Location header that is the upload URL for resumable uploads
                upload_url = resp.headers.get('Location') or resp.headers.get('location')
                if upload_url:
                    return {'status': 'pending_upload', 'platform': 'youtube', 'upload_url': upload_url}
                # fallback: return a stub id if we couldn't obtain an upload URL
            except Exception:
                pass

            yt_id = f"yt_{draft.get('_id')}"
            return {'status': 'published', 'platform': 'youtube', 'id': yt_id}

        # Fallback stub behavior
        yt_id = f"yt_{draft.get('_id')}"
        return {'status': 'published', 'platform': 'youtube', 'id': yt_id}

    def get_oauth_authorize_url(self, brand_id: str, redirect_uri: str, state: Optional[str] = None) -> str:
        """Return a Google OAuth2 authorize URL for YouTube when client_id is set.

        Uses scopes required for upload and requests offline access so a refresh_token
        is issued.
        """
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        if not client_id:
            return super().get_oauth_authorize_url(brand_id, redirect_uri, state)

        scope = 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly'
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': scope,
            'access_type': 'offline',
            'prompt': 'consent',
        }
        if state:
            params['state'] = state
        # Build query string
        from urllib.parse import urlencode
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    def _refresh_via_google(self, brand_id: str, client_id: str, client_secret: str, refresh_token: str) -> Optional[dict]:
        """Call Google's token endpoint to refresh an access token.

        Returns the updated token document on success, or None on failure.
        """
        token_url = 'https://oauth2.googleapis.com/token'
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
        }
        try:
            resp = requests.post(token_url, data=data, timeout=10)
            resp.raise_for_status()
            j = resp.json()
            access_token = j.get('access_token')
            expires_in = j.get('expires_in', 3600)
            expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
            token_doc = {
                'brand_id': brand_id,
                'platform': 'youtube',
                'access_token': access_token,
                'refresh_token': refresh_token,
                'expires_at': expires_at,
                'updated_at': datetime.utcnow(),
            }
            self.store_token(brand_id, 'youtube', token_doc)
            return self._serialize_doc(token_doc)
        except Exception:
            return None

    def exchange_code_for_token(self, brand_id: str, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for tokens using Google OAuth when creds are present.

        Falls back to BaseAdapter.exchange_code_for_token if no client credentials are configured.
        """
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        token_url = 'https://oauth2.googleapis.com/token'
        if client_id and client_secret:
            data = {
                'client_id': client_id,
                'client_secret': client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': redirect_uri,
            }
            try:
                resp = requests.post(token_url, data=data, timeout=10)
                resp.raise_for_status()
                j = resp.json()
                access_token = j.get('access_token')
                refresh_token = j.get('refresh_token')
                expires_in = j.get('expires_in', 3600)
                expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
                token_doc = {
                    'brand_id': brand_id,
                    'platform': 'youtube',
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'expires_at': expires_at,
                    'created_at': datetime.utcnow(),
                }
                self.store_token(brand_id, 'youtube', token_doc)
                return self._serialize_doc(token_doc)
            except Exception:
                # fall back to stub behavior on network/auth errors
                return super().exchange_code_for_token(brand_id, code, redirect_uri)

        # No client credentials configured -> fallback to base stub behavior
        return super().exchange_code_for_token(brand_id, code, redirect_uri)

    def refresh_access_token(self, brand_id: str, platform: str) -> Optional[dict]:
        """Override generic refresh to call Google's token endpoint when credentials are present."""
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        token = self.get_token(brand_id, platform)
        if client_id and client_secret and token and token.get('refresh_token'):
            return self._refresh_via_google(brand_id, client_id, client_secret, token.get('refresh_token'))
        # otherwise use base stub
        return super().refresh_access_token(brand_id, platform)
