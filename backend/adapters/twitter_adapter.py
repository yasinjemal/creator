from .base import BaseAdapter


class TwitterAdapter(BaseAdapter):
    def __init__(self, config=None):
        cfg = config or {}
        cfg.setdefault('platform', 'twitter')
        super().__init__(cfg)

    def publish(self, draft: dict) -> dict:
        """Publish a draft to Twitter (stub).

        Real implementation should use Twitter API and the stored tokens
        from `get_token` to authenticate. Here we simulate a publish response.
        """
        brand_id = draft.get('brand_id')
        token = self.get_token(brand_id, 'twitter')
        if not token:
            return {'status': 'error', 'error': 'no_oauth_token'}

        # Simulated tweet id
        tweet_id = f"tw_{draft.get('_id')}"
        return {'status': 'published', 'platform': 'twitter', 'id': tweet_id}
