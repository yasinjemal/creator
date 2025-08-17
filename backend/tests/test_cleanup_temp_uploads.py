import os
import time
import tempfile
import importlib.util
# Load cleanup_temp_uploads directly from backend/worker_tasks.py to avoid import path issues in container
spec = importlib.util.spec_from_file_location('worker_tasks', '/app/worker_tasks.py')
worker_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker_mod)
cleanup_temp_uploads = worker_mod.cleanup_temp_uploads


def test_cleanup_temp_uploads_removes_old_file():
    tmp_dir = tempfile.gettempdir()
    fname = os.path.join(tmp_dir, f"upload_test_{int(time.time())}")
    # create a temp file with upload_ prefix to match pattern
    with open(fname, 'wb') as fh:
        fh.write(b'test')
    # set mtime to 2 hours ago
    old_time = time.time() - (2 * 3600)
    os.utime(fname, (old_time, old_time))

    removed = cleanup_temp_uploads(age_seconds=3600, tmp_dir=tmp_dir, prefix='upload_test_')
    # cleanup should remove the file we created
    assert any(fname == p for p in removed), f"Expected {fname} in removed list, got {removed}"
    # file should no longer exist
    assert not os.path.exists(fname)
