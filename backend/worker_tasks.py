import os
from datetime import datetime, timedelta
import os
from redis import Redis
from rq import Queue
from pymongo import MongoClient


def _get_db():
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017/creatorflow')
    client = MongoClient(mongo_uri)
    return client.get_default_database()


def publish_draft(draft: dict):
    """
    Simulate publishing a draft. In production this would call platform adapters.
    Persist publish result (status, published_at) into the drafts collection.
    """
    db = _get_db()
    brand_id = draft.get('brand_id')
    draft_id = draft.get('_id')
    print(f"Publishing draft for brand {brand_id}")

    adapter_result = None
    platform = draft.get('platform')
    try:
        if platform == 'instagram':
            from adapters.instagram_adapter import InstagramAdapter
            adapter = InstagramAdapter()
            adapter_result = adapter.publish(draft)
        elif platform == 'twitter':
            from adapters.twitter_adapter import TwitterAdapter
            adapter = TwitterAdapter()
            adapter_result = adapter.publish(draft)
        elif platform == 'tiktok':
            from adapters.tiktok_adapter import TikTokAdapter
            adapter = TikTokAdapter()
            adapter_result = adapter.publish(draft)
        elif platform == 'youtube':
            from adapters.youtube_adapter import YouTubeAdapter
            adapter = YouTubeAdapter()
            adapter_result = adapter.publish(draft)
    except Exception as e:
        print('Adapter publish failed:', e)

    # If adapter returned an upload_url for resumable upload, enqueue the upload job
    try:
        if adapter_result and isinstance(adapter_result, dict) and adapter_result.get('status') == 'pending_upload':
            upload_url = adapter_result.get('upload_url')
            # create a queue using same Redis convention as app
            redis_host = os.getenv('REDIS_HOST', 'redis')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            q = Queue(connection=Redis(host=redis_host, port=redis_port))
            # Enqueue perform_resumable_upload with draft and upload_url; file_path optional
            job = q.enqueue('worker_tasks.perform_resumable_upload', draft, upload_url)
            print('Enqueued resumable upload job', job.get_id())
    except Exception as e:
        print('Failed to enqueue resumable upload job', str(e))

    if adapter_result is not None:
        result = {'status': 'published', 'published_at': datetime.utcnow(), 'publish_meta': adapter_result}
    else:
        # Simulated publish result
        result = {
            'status': 'published',
            'published_at': datetime.utcnow(),
            'publish_meta': {
                'platform': draft.get('platform'),
                'note': 'simulated publish - replace with real adapter'
            }
        }

    # update the draft document with publish result
    try:
        db.drafts.update_one({'_id': draft_id}, {'$set': result})
    except Exception as e:
        print('Failed to persist publish result for draft', draft_id, str(e))

    return result


def perform_resumable_upload(draft: dict, upload_url: str, file_path: str = None):
    """Perform a resumable upload to the provided upload_url.

    For demo purposes this will do a single-request upload of the file
    contents if file_path is given and small. In production, implement
    chunked/resumable logic per Google's resumable upload protocol.
    """
    import requests
    try:
        headers = {'Content-Type': 'application/octet-stream'}
        if file_path:
            with open(file_path, 'rb') as fh:
                resp = requests.put(upload_url, data=fh, headers=headers, timeout=60)
        else:
            # No file provided; send empty body to complete stub flow
            resp = requests.put(upload_url, data=b'', headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            # Completed upload - return final video id if available from API
            # cleanup temporary file if one was provided
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            result = {'status': 'published', 'platform': 'youtube', 'id': resp.headers.get('X-YouTube-Resource-Id') or 'yt_uploaded'}
            try:
                db = _get_db()
                draft_id = draft.get('_id')
                db.drafts.update_one({'_id': draft_id}, {'$set': {'status': 'published', 'publish_meta': result}})
            except Exception:
                pass
            return result
        else:
            return {'status': 'error', 'http_status': resp.status_code, 'body': resp.text}
    except Exception as e:
        # Attempt to record error state on the draft if possible
        try:
            db = _get_db()
            draft_id = draft.get('_id')
            db.drafts.update_one({'_id': draft_id}, {'$set': {'status': 'error', 'publish_error': str(e)}})
        except Exception:
            pass
        return {'status': 'error', 'error': str(e)}


def rotate_tokens(cutoff_seconds: int = 300):
    """Refresh any tokens that expire within `cutoff_seconds` from now.

    This is a best-effort function intended to be scheduled periodically.
    It scans `platform_tokens` for tokens where expires_at <= now + cutoff and
    attempts to refresh them using the platform adapter.
    """
    db = _get_db()
    now = datetime.utcnow()
    threshold = now + timedelta(seconds=cutoff_seconds)
    cursor = db.platform_tokens.find({'expires_at': {'$lte': threshold}})
    refreshed = []
    for t in cursor:
        brand_id = t.get('brand_id')
        platform = t.get('platform')
        try:
            Adapter = None
            try:
                mod = __import__(f"adapters.{platform}_adapter", fromlist=[None])
                Adapter = getattr(mod, f"{platform.capitalize()}Adapter", None)
            except Exception:
                Adapter = None
            adapter = Adapter({'platform': platform}) if Adapter else None
            if adapter:
                res = adapter.refresh_access_token(brand_id, platform)
                if res:
                    refreshed.append({'brand_id': brand_id, 'platform': platform})
        except Exception:
            continue
    return refreshed


def persist_admin_audit_event(doc: dict):
    """Persist an admin audit event into Mongo (executed by a worker via RQ).

    This function is intentionally simple and will swallow errors to avoid
    failing jobs uncontrollably; the RQ job can be retried according to queue policy.
    """
    db = _get_db()
    try:
        # Ensure ts is a datetime
        if 'ts' in doc and isinstance(doc['ts'], str):
            try:
                from datetime import datetime
                doc['ts'] = datetime.fromisoformat(doc['ts'])
            except Exception:
                doc['ts'] = datetime.utcnow()
        if 'ts' not in doc:
            from datetime import datetime
            doc['ts'] = datetime.utcnow()
        db.admin_audit.insert_one(doc)
        return True
    except Exception as e:
        # Log and return False so job can be retried externally if desired
        print('persist_admin_audit_event failed:', e)
        return False


def cleanup_temp_uploads(age_seconds: int = 3600, tmp_dir: str = None, prefix: str = 'upload_'):
    """Remove temporary upload files older than `age_seconds` from `tmp_dir`.

    This is a simple cleanup helper intended to be run periodically (cron/RQ job).
    It looks for files starting with `prefix` in the tmp dir and deletes those
    with modification time older than `age_seconds`. Returns list of removed paths.
    """
    import time, glob, tempfile
    if tmp_dir is None:
        tmp_dir = tempfile.gettempdir()
    removed = []
    now = time.time()
    pattern = os.path.join(tmp_dir, f"{prefix}*")
    for path in glob.glob(pattern):
        try:
            mtime = os.path.getmtime(path)
            if now - mtime > float(age_seconds):
                try:
                    os.remove(path)
                    removed.append(path)
                except Exception:
                    # ignore failures to delete single files
                    continue
        except Exception:
            continue
    # optional logging
    if removed:
        print('cleanup_temp_uploads removed:', removed)
    return removed
