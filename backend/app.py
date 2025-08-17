import os
from flask import Flask, jsonify, request
from dotenv import load_dotenv
from pymongo import MongoClient
import uuid
from rq import Queue
from redis import Redis
import time
from services.content_service import generate_content
from adapters.base import BaseAdapter
from datetime import datetime

load_dotenv()
# Prefer Docker secret files for sensitive provider credentials when available.
# If the environment variable is not set, attempt to load from mounted secret files
# commonly placed under /run/secrets/<name> by Docker Compose.
def _load_secret_to_env(var_name: str, secret_path: str):
    try:
        if os.getenv(var_name):
            return
        if os.path.exists(secret_path):
            with open(secret_path, 'r', encoding='utf8') as f:
                val = f.read().strip()
                if val:
                    os.environ[var_name] = val
    except Exception:
        # Fail silently; existing env vars (if any) will be used.
        pass

# Load Google client credentials from secrets if present (dev/production friendly)
_load_secret_to_env('GOOGLE_CLIENT_ID', '/run/secrets/google_client_id')
_load_secret_to_env('GOOGLE_CLIENT_SECRET', '/run/secrets/google_client_secret')


def _audit_admin_event(req, action: str, status: str, detail: str = ''):
    """Insert an audit record for admin actions (best-effort)."""
    try:
        doc = {
            'ts': datetime.utcnow(),
            'remote_addr': getattr(req, 'remote_addr', None),
            'path': getattr(req, 'path', None),
            'method': getattr(req, 'method', None),
            'action': action,
            'status': status,
            'detail': detail,
        }
        # Mask header values
        hdr = req.headers.get('X-Admin-Key')
        if hdr:
            doc['admin_key_masked'] = (str(hdr)[:4] + '...') if len(str(hdr)) > 4 else '***'
        # Attempt to enqueue a durable RQ job to persist the audit event cross-process
        try:
            redis_host = os.getenv('REDIS_HOST', 'redis')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            q = Queue(connection=Redis(host=redis_host, port=redis_port))
            # enqueue worker_tasks.persist_admin_audit_event
            q.enqueue('worker_tasks.persist_admin_audit_event', doc)
            return
        except Exception:
            # fallback to direct insert (best-effort)
            try:
                db.admin_audit.insert_one(doc)
            except Exception:
                pass
    except Exception:
        pass


def _is_admin_request(req) -> bool:
    """Return True if request presents valid admin credentials.

    Supports two modes:
    - Token mode: header 'X-Admin-Key' must match env ADMIN_API_KEY
    - Basic auth mode: HTTP Basic auth username/password match ADMIN_USER/ADMIN_PASS
    """
    # Token mode
    admin_key = os.getenv('ADMIN_API_KEY')
    if admin_key:
        # Header name case-insensitive in Flask
        hdr = req.headers.get('X-Admin-Key') or req.headers.get('X-ADMIN-KEY')
        if hdr and hdr == admin_key:
            return True

    # Basic auth fallback
    admin_user = os.getenv('ADMIN_USER')
    admin_pass = os.getenv('ADMIN_PASS')
    if admin_user and admin_pass:
        auth = req.authorization
        if auth and auth.username == admin_user and auth.password == admin_pass:
            return True

    return False


# Redis-backed rate limiter for admin endpoints. Uses ADMIN_RATE_LIMIT and ADMIN_RATE_WINDOW env vars.
import functools

def rate_limited(func):
    """Decorator to rate-limit calls using a Redis-backed token-bucket implemented via Lua.

    Uses ADMIN_RATE_LIMIT (max tokens) and ADMIN_RATE_WINDOW (ms window to fully refill).
    Keying: admin key (X-Admin-Key) if present, otherwise client IP.
    If Redis is unavailable the check is best-effort (request allowed).
    """

    # Lua script: atomically refill tokens based on elapsed ms and allow if >= requested
    lua_script = r"""
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local expire_ms = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = max_tokens end
if ts == nil then ts = now end

local delta = now - ts
if delta > 0 then
  local add = delta * refill_per_ms
  tokens = tokens + add
  if tokens > max_tokens then tokens = max_tokens end
  ts = now
end

local allowed = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tostring(tokens), 'ts', tostring(ts))
redis.call('PEXPIRE', key, expire_ms)
return {allowed, tostring(tokens)}
"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            max_tokens = int(os.getenv('ADMIN_RATE_LIMIT', '60'))
            window_sec = int(os.getenv('ADMIN_RATE_WINDOW', '60'))
        except Exception:
            max_tokens, window_sec = 60, 60

        # Compute refill rate per ms (tokens per ms) so window_sec brings tokens from 0->max
        window_ms = max(1, window_sec * 1000)
        refill_per_ms = float(max_tokens) / float(window_ms)

        hdr = request.headers.get('X-Admin-Key') or request.headers.get('X-ADMIN-KEY')
        if hdr:
            ident = f"admin:{hdr}"
        else:
            ident = f"ip:{request.remote_addr}"

        redis_key = f"creatorflow:admin_tb:{ident}"
        now_ms = int(time.time() * 1000)
        try:
            # eval returns [allowed, tokens]
            res = redis_conn.eval(lua_script, 1, redis_key, str(max_tokens), str(refill_per_ms), str(now_ms), '1', str(window_ms * 2))
            # res[1] == allowed (1/0) - be robust to bytes/int/string
            allowed = 1
            if res and len(res) > 0:
                raw = res[0]
                try:
                    allowed = int(raw)
                except Exception:
                    try:
                        allowed = int(raw.decode())
                    except Exception:
                        allowed = 1
            if allowed != 1:
                # audit rate-limited attempt
                try:
                    _audit_admin_event(request, action='rate_limited', status='429', detail=f'limit={max_tokens},window={window_sec}')
                except Exception:
                    pass
                return jsonify({'error': 'rate_limited', 'limit': max_tokens, 'window_seconds': window_sec}), 429
        except Exception:
            # On Redis errors, allow the request to avoid accidental lockout
            pass

        return func(*args, **kwargs)
    return wrapper


def require_admin(func):
    """Decorator to require admin credentials using `_is_admin_request`."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not _is_admin_request(request):
            try:
                _audit_admin_event(request, action='auth', status='401', detail='unauthorized')
            except Exception:
                pass
            return jsonify({'error': 'unauthorized'}), 401
        else:
            # record successful auth (mask key info)
            try:
                _audit_admin_event(request, action='auth', status='200', detail='authorized')
            except Exception:
                pass
        return func(*args, **kwargs)
    return wrapper

app = Flask(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017/creatorflow")
client = MongoClient(MONGO_URI)
db = client.get_default_database()
redis_conn = Redis(host=os.getenv('REDIS_HOST', 'redis'), port=int(os.getenv('REDIS_PORT', 6379)))
q = Queue(connection=redis_conn)

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/api/brand", methods=["POST"])
def create_brand():
    data = request.json
    if not data or "name" not in data:
        return jsonify({"error": "name is required"}), 400
    brand = {"_id": str(uuid.uuid4()), "name": data["name"], "voice": data.get("voice", {}), "assets": data.get("assets", {})}
    db.brands.insert_one(brand)
    return jsonify(brand), 201

@app.route("/api/brand/<brand_id>", methods=["GET"])
def get_brand(brand_id):
    brand = db.brands.find_one({"_id": brand_id})
    if not brand:
        return jsonify({"error": "not found"}), 404
    brand["_id"] = str(brand.get("_id"))
    return jsonify(brand)


@app.route("/api/content/generate", methods=["POST"])
def api_generate():
    data = request.json or {}
    brand_id = data.get('brand_id')
    platform = data.get('platform', 'instagram')
    if not brand_id:
        return jsonify({'error': 'brand_id required'}), 400
    brand = db.brands.find_one({'_id': brand_id})
    if not brand:
        return jsonify({'error': 'brand not found'}), 404

    result = generate_content(brand, platform, data.get('overrides'))
    # store draft with string id
    draft = {'_id': str(uuid.uuid4()), 'brand_id': brand_id, 'platform': platform, 'payload': result}
    db.drafts.insert_one(draft)
    return jsonify(draft)


@app.route('/api/content/schedule', methods=['POST'])
def api_schedule():
    data = request.json or {}
    draft_id = data.get('draft_id')
    post_time = data.get('post_time')
    if not draft_id or not post_time:
        return jsonify({'error': 'draft_id and post_time required'}), 400
    draft = db.drafts.find_one({'_id': draft_id})
    if not draft:
        return jsonify({'error': 'draft not found'}), 404

    # enqueue a job that would run at scheduled time (simple immediate enqueue for demo)
    # enqueue the publish task defined in worker_tasks.py
    job = q.enqueue('worker_tasks.publish_draft', draft)
    return jsonify({'job_id': job.get_id(), 'status': 'queued'})


@app.route('/api/content/publish', methods=['POST'])
def api_publish():
    """Publish a draft immediately. Accepts multipart form with draft_id and optional file.

    If the platform adapter returns a resumable upload URL, this endpoint will
    save the uploaded file to a temporary path and enqueue `perform_resumable_upload`
    with the file path so the worker can perform the upload.
    """
    # form-data: draft_id, file (optional)
    draft_id = request.form.get('draft_id')
    if not draft_id:
        return jsonify({'error': 'draft_id required'}), 400

    draft = db.drafts.find_one({'_id': draft_id})
    if not draft:
        return jsonify({'error': 'draft not found'}), 404

    platform = draft.get('platform', 'youtube')
    # instantiate adapter
    try:
        AdapterCls = __import__(f"adapters.{platform}_adapter", fromlist=[None])
        Adapter = getattr(AdapterCls, f"{platform.capitalize()}Adapter", None)
        adapter = Adapter({'platform': platform}) if Adapter else BaseAdapter({'platform': platform})
    except Exception:
        adapter = BaseAdapter({'platform': platform})

    # Ask the adapter to prepare a publish; it may return an upload_url for resumable uploads
    try:
        adapter_result = adapter.publish(draft)
    except Exception as e:
        # Return adapter error as a normal result so callers/tests can handle it.
        adapter_result = {'status': 'error', 'error': str(e)}

    # If adapter asked for a resumable upload, handle file saving and enqueue upload job
    if isinstance(adapter_result, dict) and adapter_result.get('status') == 'pending_upload':
        upload_url = adapter_result.get('upload_url')
        if not upload_url:
            return jsonify({'error': 'no_upload_url_from_adapter'}), 500

        # file may be in request.files
        file = request.files.get('file')
        if not file:
            # enqueue upload job without file (worker will perform empty-body PUT)
            job = q.enqueue('worker_tasks.perform_resumable_upload', draft, upload_url, None)
            return jsonify({'job_id': job.get_id(), 'status': 'upload_queued', 'note': 'no file provided'}), 202

        # save to temporary file path and enqueue job with file_path
        # Server-side validation: size and allowed types
        try:
            MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '512'))
        except Exception:
            MAX_UPLOAD_MB = 512
        allowed_exts = {'mp4', 'mov', 'webm', 'mkv'}

        filename = getattr(file, 'filename', '') or ''
        file_ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

        # rough size check: try content_length, otherwise inspect stream
        size_bytes = None
        try:
            size_bytes = int(request.content_length) if request.content_length else None
        except Exception:
            size_bytes = None

        if size_bytes is None:
            try:
                # fallback: seek to compute size
                file.stream.seek(0, 2)
                size_bytes = file.stream.tell()
                file.stream.seek(0)
            except Exception:
                size_bytes = None

        if size_bytes is not None and size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
            return jsonify({'ok': False, 'code': 'payload_too_large', 'message': f'file exceeds {MAX_UPLOAD_MB}MB limit'}), 413

        if file_ext not in allowed_exts:
            return jsonify({'ok': False, 'code': 'unsupported_media_type', 'message': f'allowed types: {", ".join(sorted(allowed_exts))}'}), 415

        # basic metadata validation for YouTube: require snippet/title at least
        if draft.get('platform') == 'youtube':
            snippet = draft.get('payload', {}).get('snippet')
            if not snippet or not snippet.get('title'):
                return jsonify({'ok': False, 'code': 'invalid_metadata', 'message': 'missing snippet.title in draft payload'}), 400

        try:
            import tempfile
            tmp_dir = tempfile.gettempdir()
            tmp_name = f"upload_{uuid.uuid4().hex}"
            tmp_path = os.path.join(tmp_dir, tmp_name)
            file.save(tmp_path)
            job = q.enqueue('worker_tasks.perform_resumable_upload', draft, upload_url, tmp_path)
            return jsonify({'job_id': job.get_id(), 'status': 'upload_queued'}), 202
        except Exception as e:
            return jsonify({'ok': False, 'code': 'failed_to_save_file', 'message': str(e)}), 500

    # Otherwise return adapter result (published or error)
    # If adapter returned a non-pending result, persist it into the draft so UI/tests observe status
    try:
        if isinstance(adapter_result, dict) and adapter_result.get('status') != 'pending_upload':
            result_doc = {'status': adapter_result.get('status'), 'publish_meta': adapter_result}
            if adapter_result.get('status') == 'published':
                result_doc['published_at'] = datetime.utcnow()
            db.drafts.update_one({'_id': draft_id}, {'$set': result_doc})
    except Exception:
        pass

    return jsonify({'result': adapter_result}), 200


@app.route('/api/drafts', methods=['GET'])
def list_drafts():
    items = list(db.drafts.find({}))
    for it in items:
        it['_id'] = str(it.get('_id'))
    return jsonify(items)


@app.route('/api/oauth/<platform>/authorize', methods=['GET'])
def oauth_authorize(platform):
    """Return an authorization URL to begin OAuth for a brand.

    Query params: brand_id, redirect_uri, optional state
    """
    brand_id = request.args.get('brand_id')
    redirect_uri = request.args.get('redirect_uri')
    state = request.args.get('state')
    if not brand_id or not redirect_uri:
        return jsonify({'error': 'brand_id and redirect_uri required'}), 400

    # create a base adapter instance for this platform and return the URL
    adapter = BaseAdapter({'platform': platform})
    url = adapter.get_oauth_authorize_url(brand_id, redirect_uri, state)
    return jsonify({'authorize_url': url})


@app.route('/api/oauth/<platform>/callback', methods=['POST'])
def oauth_callback(platform):
    """Exchange an authorization code for tokens and store them.

    Body params: brand_id, code, redirect_uri
    """
    data = request.json or {}
    brand_id = data.get('brand_id')
    code = data.get('code')
    redirect_uri = data.get('redirect_uri')
    if not brand_id or not code or not redirect_uri:
        return jsonify({'error': 'brand_id, code and redirect_uri required'}), 400

    # instantiate a platform-specific adapter if available, otherwise BaseAdapter
    try:
        AdapterCls = __import__(f"adapters.{platform}_adapter", fromlist=[None])
        Adapter = getattr(AdapterCls, f"{platform.capitalize()}Adapter", None)
        adapter = Adapter({'platform': platform}) if Adapter else BaseAdapter({'platform': platform})
    except Exception:
        adapter = BaseAdapter({'platform': platform})

    token_doc = adapter.exchange_code_for_token(brand_id, code, redirect_uri)
    return jsonify({'token': token_doc})


@app.route('/api/oauth/<platform>/refresh', methods=['POST'])
def oauth_refresh(platform):
    """Trigger a token refresh for brand/platform. Body: {brand_id}

    If provider-specific refresh is available (e.g. YouTube) it will be used.
    """
    data = request.json or {}
    brand_id = data.get('brand_id')
    if not brand_id:
        return jsonify({'error': 'brand_id required'}), 400

    # Use BaseAdapter refresh stub which will call provider-specific logic if implemented
    try:
        AdapterCls = __import__(f"adapters.{platform}_adapter", fromlist=[None])
        Adapter = getattr(AdapterCls, f"{platform.capitalize()}Adapter", None)
        adapter = Adapter({'platform': platform}) if Adapter else BaseAdapter({'platform': platform})
    except Exception:
        adapter = BaseAdapter({'platform': platform})

    refreshed = adapter.refresh_access_token(brand_id, platform)
    if not refreshed:
        return jsonify({'error': 'refresh_failed_or_no_token'}), 400
    return jsonify({'token': refreshed})


@app.route('/api/oauth/<platform>/status', methods=['GET'])
def oauth_status(platform):
    """Return a masked token status for a brand/platform.

    Query params: brand_id
    The response intentionally masks access/refresh tokens and returns expiry metadata.
    """
    brand_id = request.args.get('brand_id')
    if not brand_id:
        return jsonify({'error': 'brand_id required'}), 400

    # instantiate a platform-specific adapter if available, otherwise BaseAdapter
    try:
        AdapterCls = __import__(f"adapters.{platform}_adapter", fromlist=[None])
        Adapter = getattr(AdapterCls, f"{platform.capitalize()}Adapter", None)
        adapter = Adapter({'platform': platform}) if Adapter else BaseAdapter({'platform': platform})
    except Exception:
        adapter = BaseAdapter({'platform': platform})

    token = adapter.get_token(brand_id, platform)
    if not token:
        return jsonify({'connected': False})

    # Compute expiry seconds if possible, then serialize and mask sensitive fields
    expires_in = None
    try:
        if token.get('expires_at'):
            # token may be a datetime object
            from datetime import datetime
            exp = token.get('expires_at')
            if isinstance(exp, str):
                try:
                    exp_dt = datetime.fromisoformat(exp)
                except Exception:
                    exp_dt = None
            else:
                exp_dt = exp
            if exp_dt:
                expires_in = max(0, int((exp_dt - datetime.utcnow()).total_seconds()))
    except Exception:
        expires_in = None

    doc = adapter._serialize_doc(token)
    # Mask any raw token values
    for k in ('access_token', 'refresh_token'):
        if k in doc:
            doc[k] = '*****'

    resp = {'connected': True, 'platform': platform, 'token': doc}
    if expires_in is not None:
        resp['expires_in'] = expires_in
    return jsonify(resp)


@app.route('/api/admin/oauth/health', methods=['GET'])
@require_admin
@rate_limited
def admin_oauth_health():
    """Return a masked, annotated connection health summary for all brands.

    Response shape: [{ brand_id, name, connections: [{ platform, connected, expires_in, token: {masked fields}, raw_doc_summary }] }]
    """
    try:
        # Load all brands
        brands = list(db.brands.find({}))
        # Map brand_id -> name
        brand_map = {str(b.get('_id')): b.get('name') for b in brands}

        # Scan platform_tokens to discover which platforms each brand has entries for
        summary = {}
        for doc in db.platform_tokens.find({}):
            try:
                brand_id = doc.get('brand_id')
                platform = doc.get('platform')
                if not brand_id or not platform:
                    continue

                # instantiate adapter for platform
                try:
                    AdapterCls = __import__(f"adapters.{platform}_adapter", fromlist=[None])
                    Adapter = getattr(AdapterCls, f"{platform.capitalize()}Adapter", None)
                    adapter = Adapter({'platform': platform}) if Adapter else BaseAdapter({'platform': platform})
                except Exception:
                    adapter = BaseAdapter({'platform': platform})

                # Use adapter.get_token to obtain decrypted token if available
                token = adapter.get_token(brand_id, platform)

                # Compute expires_in where possible
                expires_in = None
                try:
                    if token and token.get('expires_at'):
                        from datetime import datetime
                        exp = token.get('expires_at')
                        if isinstance(exp, str):
                            try:
                                exp_dt = datetime.fromisoformat(exp)
                            except Exception:
                                exp_dt = None
                        else:
                            exp_dt = exp
                        if exp_dt:
                            expires_in = max(0, int((exp_dt - datetime.utcnow()).total_seconds()))
                except Exception:
                    expires_in = None

                token_doc = None
                if token:
                    token_doc = adapter._serialize_doc(token)
                    for k in ('access_token', 'refresh_token'):
                        if k in token_doc:
                            token_doc[k] = '*****'

                entry = {
                    'platform': platform,
                    'connected': bool(token),
                    'expires_in': expires_in,
                    'token': token_doc,
                    # include a lightweight raw doc summary for ops without leaking secrets
                    'raw_doc_summary': {k: str(v) for k, v in (doc or {}).items() if k not in ('access_token', 'refresh_token')}
                }

                summary.setdefault(brand_id, []).append(entry)
            except Exception:
                # continue scanning other docs
                continue

        # Build response list including brands without tokens
        out = []
        # include brands from brands collection
        for bid, name in brand_map.items():
            out.append({'brand_id': bid, 'name': name, 'connections': summary.get(bid, [])})

        # Include any brands that appeared in tokens but not in brands collection
        for bid in summary.keys():
            if bid not in brand_map:
                out.append({'brand_id': bid, 'name': None, 'connections': summary.get(bid, [])})

        return jsonify(out)
    except Exception as e:
        return jsonify({'error': 'internal_error', 'detail': str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
