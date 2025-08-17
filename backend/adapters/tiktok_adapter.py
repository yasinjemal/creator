from .base import BaseAdapter


class TikTokAdapter(BaseAdapter):
    def __init__(self, config=None):
        cfg = config or {}
        cfg.setdefault('platform', 'tiktok')
        super().__init__(cfg)

    def publish(self, draft: dict) -> dict:
        """Publish a draft to TikTok (stub).

        Real implementation should upload video assets via TikTok's API using
        stored OAuth tokens. This stub checks for tokens and returns a fake id.
        """
        brand_id = draft.get('brand_id')
        token = self.get_token(brand_id, 'tiktok')
        if not token:
            return {'status': 'error', 'error': 'no_oauth_token'}

        tt_id = f"tt_{draft.get('_id')}"
        return {'status': 'published', 'platform': 'tiktok', 'id': tt_id}
