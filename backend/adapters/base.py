from typing import Dict, Any, Optional
import os
from datetime import datetime, timedelta
from pymongo import MongoClient
import base64
import hashlib


def _get_db():
    """Get a pymongo database using MONGO_URI env var (same convention as other modules)."""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017/creatorflow')
    client = MongoClient(mongo_uri)
    return client.get_default_database()


def _get_fernet():
    """Return a Fernet instance if ENCRYPTION_KEY is set and cryptography is available.

    The ENCRYPTION_KEY may be either a 32-byte urlsafe-base64 key (Fernet native), or
    an arbitrary passphrase; if the latter, we derive a Fernet-compatible key by
    hashing with SHA-256 and urlsafe-base64-encoding the result.
    """
    # Prefer Docker secret file if present (mounted at /run/secrets/encryption_key)
    key_file = os.getenv('ENCRYPTION_KEY_FILE', '/run/secrets/encryption_key')
    key = None
    try:
        if os.path.exists(key_file):
            with open(key_file, 'r') as f:
                key = f.read().strip()
    except Exception:
        key = None
    # Fallback to legacy ENCRYPTION_KEY env var
    if not key:
        key = os.getenv('ENCRYPTION_KEY')
    if not key:
        return None
    try:
        # import here to avoid hard dependency at module import time if not needed
        from cryptography.fernet import Fernet
    except Exception:
        return None

    # If user supplied a passphrase, derive a proper 32-byte base64-encoded key
    try:
        if isinstance(key, str) and len(key) != 44:
            key_bytes = hashlib.sha256(key.encode()).digest()
            key = base64.urlsafe_b64encode(key_bytes)
        # Ensure bytes
        if isinstance(key, str):
            key = key.encode()
        return Fernet(key)
    except Exception:
        return None


def _encrypt_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    f = _get_fernet()
    if not f:
        return value
    try:
        return f.encrypt(value.encode()).decode()
    except Exception:
        return value


def _decrypt_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    f = _get_fernet()
    if not f:
        return value
    try:
        # value might already be plaintext; attempt decrypt and fall back to original
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value


class BaseAdapter:
    """Base adapter interface for platform integrations.

    This class also provides light-weight OAuth token helpers that store
    access/refresh tokens in a `platform_tokens` collection keyed by
    (brand_id, platform). These are simple stubs meant for local/dev use
    and should be replaced with secure vault-backed storage in production.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def publish(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Publish draft to platform. Must be implemented by adapters."""
        raise NotImplementedError()

    # --- OAuth/token helpers (generic stubs) ---
    def get_oauth_authorize_url(self, brand_id: str, redirect_uri: str, state: Optional[str] = None) -> str:
        """Return a provider-specific authorization URL (stub).

        Consumers should redirect users to this URL to begin OAuth.
        """
        platform = self.config.get('platform', 'unknown')
        state_q = f"&state={state}" if state else ""
        # In a real adapter this would include client_id, scopes, and provider host.
        return f"https://auth.{platform}.example.com/oauth/authorize?redirect_uri={redirect_uri}{state_q}"

    def exchange_code_for_token(self, brand_id: str, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange an OAuth code for tokens (stub) and persist them.

        This simulates a token response and writes it to the database via
        `store_token`.
        """
        platform = self.config.get('platform', 'unknown')
        access_token = f"stub_access_{platform}_{brand_id}_{code}"
        refresh_token = f"stub_refresh_{platform}_{brand_id}_{code}"
        expires_at = datetime.utcnow() + timedelta(hours=1)
        token_doc = {
            'brand_id': brand_id,
            'platform': platform,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_at': expires_at,
            'created_at': datetime.utcnow(),
        }
        self.store_token(brand_id, platform, token_doc)
        return self._serialize_doc(token_doc)

    def refresh_access_token(self, brand_id: str, platform: str) -> Optional[Dict[str, Any]]:
        """Refresh access token using stored refresh_token (generic stub).

        Provider-specific adapters should override this to call the real
        provider token endpoint. This generic implementation will simulate a
        refresh when a refresh_token exists.
        """
        token = self.get_token(brand_id, platform)
        if not token or not token.get('refresh_token'):
            return None

        # Simulate refresh by rotating access token and extending expiry.
        access_token = f"stub_refreshed_access_{platform}_{brand_id}_{int(datetime.utcnow().timestamp())}"
        expires_at = datetime.utcnow() + timedelta(hours=1)
        token.update({'access_token': access_token, 'expires_at': expires_at, 'refreshed_at': datetime.utcnow()})
        self.store_token(brand_id, platform, token)
        return self._serialize_doc(token)

    def _serialize_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Return a JSON-safe copy of a token/doc by converting datetimes and ObjectIds.

        This is intentionally conservative — production code should centralize
        serialization rules or use an ODM.
        """
        out = {}
        for k, v in (doc or {}).items():
            # datetime -> isoformat
            if isinstance(v, datetime):
                out[k] = v.isoformat()
            # primitive types pass through
            elif isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
            else:
                # convert ObjectId and other complex types to string to ensure JSON serializable
                try:
                    out[k] = str(v)
                except Exception:
                    out[k] = None
        return out

    def store_token(self, brand_id: str, platform: str, token: Dict[str, Any]):
        """Upsert token document into `platform_tokens` collection."""
        db = _get_db()
        try:
            # If encryption is enabled, encrypt sensitive fields before storing
            store_doc = dict(token or {})
            for k in ('access_token', 'refresh_token'):
                if k in store_doc:
                    store_doc[k] = _encrypt_value(store_doc[k])

            db.platform_tokens.update_one(
                {'brand_id': brand_id, 'platform': platform},
                {'$set': store_doc},
                upsert=True,
            )
        except Exception:
            # Fail silently in dev; callers should handle missing tokens gracefully.
            pass

    def get_token(self, brand_id: str, platform: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored token document for a brand/platform, or None."""
        db = _get_db()
        try:
            doc = db.platform_tokens.find_one({'brand_id': brand_id, 'platform': platform})
            if not doc:
                return None
            # Decrypt token fields if needed
            for k in ('access_token', 'refresh_token'):
                if k in doc:
                    doc[k] = _decrypt_value(doc[k])
            return doc
        except Exception:
            return None

    def revoke_token(self, brand_id: str, platform: str) -> bool:
        """Revoke (delete) stored token. Returns True if deleted."""
        db = _get_db()
        try:
            res = db.platform_tokens.delete_one({'brand_id': brand_id, 'platform': platform})
            return (res.deleted_count or 0) > 0
        except Exception:
            return False
