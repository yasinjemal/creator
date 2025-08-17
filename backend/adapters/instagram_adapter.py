from .base import BaseAdapter


class InstagramAdapter(BaseAdapter):
    def __init__(self, config=None):
        cfg = config or {}
        cfg.setdefault('platform', 'instagram')
        super().__init__(cfg)

    def publish(self, draft: dict) -> dict:
        # Stub: integrate with Instagram Graph API here. Use stored tokens.
        brand_id = draft.get('brand_id')
        token = self.get_token(brand_id, 'instagram')
        if not token:
            return {'status': 'error', 'error': 'no_oauth_token'}

        return {"status": "published", "platform": "instagram", "id": f"ig_{draft.get('_id')}"}
