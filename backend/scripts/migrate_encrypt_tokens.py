#!/usr/bin/env python3
"""Migration: encrypt plaintext token fields in platform_tokens with Fernet.

Usage:
  python migrate_encrypt_tokens.py --dry-run
  python migrate_encrypt_tokens.py --apply

This script:
 - Dry-run: counts candidates and prints summary.
 - Backup: copies platform_tokens -> platform_tokens_backup_{ts}
 - Apply: encrypts access_token, refresh_token, and token_json nested fields when they are not already Fernet (prefix 'gAAAA').
 - Batches updates (~500) with majority writeConcern and retryWrites.
 - Logs totals and samples; verifies random sample decrypts after update.
"""
from __future__ import annotations
import os
import sys
import time
import argparse
import random
import json
from datetime import datetime
from typing import Any, Dict, List

from pymongo import MongoClient, WriteConcern
from pymongo.errors import PyMongoError

try:
    # Prefer to reuse adapter helper for Fernet acquisition if available
    from adapters import base as adapter_base
    _get_fernet = getattr(adapter_base, '_get_fernet', None)
except Exception:
    _get_fernet = None


def get_fernet():
    if _get_fernet:
        f = _get_fernet()
        return f
    # Fallback: derive key from env like base._get_fernet
    from cryptography.fernet import Fernet
    key = os.getenv('ENCRYPTION_KEY')
    if not key:
        # check secret file
        key_file = os.getenv('ENCRYPTION_KEY_FILE', '/run/secrets/encryption_key')
        try:
            if os.path.exists(key_file):
                with open(key_file, 'r') as f:
                    key = f.read().strip()
        except Exception:
            key = None
    if not key:
        raise RuntimeError('No encryption key found in ENCRYPTION_KEY or secret file')
    # ensure bytes
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def connect_db():
    uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017/creatorflow')
    client = MongoClient(uri)
    db = client.get_default_database()
    return db


def is_encrypted_value(val: Any) -> bool:
    # Fernet tokens typically start with 'gAAAA'
    return isinstance(val, str) and val.startswith('gAAAA')


def find_candidates(coll, batch_size=500):
    # Find documents that have plaintext tokens (not starting with gAAAA)
    query = {
        '$or': [
            {'access_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
            {'refresh_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
            {'token_json.access_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
            {'token_json.refresh_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
        ]
    }
    return coll.find(query, batch_size=batch_size)


def backup_collection(db, src='platform_tokens'):
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    dst = f'{src}_backup_{ts}'
    src_coll = db[src]
    dst_coll = db[dst]
    docs = list(src_coll.find({}))
    if docs:
        dst_coll.insert_many(docs)
    return dst, len(docs)


def migrate(db, fernet, batch_size=500):
    coll = db.platform_tokens.with_options(write_concern=WriteConcern(w='majority', wtimeout=10000))
    cursor = find_candidates(coll, batch_size=batch_size)
    total_scanned = 0
    total_updated = 0
    total_skipped = 0
    sample_ids = []
    start = time.time()
    batch = []
    for doc in cursor:
        total_scanned += 1
        _id = doc.get('_id')
        orig = {}
        updates = {}
        # access_token
        at = doc.get('access_token')
        if at and not is_encrypted_value(at):
            updates['access_token'] = fernet.encrypt(at.encode()).decode()
        # refresh_token
        rt = doc.get('refresh_token')
        if rt and not is_encrypted_value(rt):
            updates['refresh_token'] = fernet.encrypt(rt.encode()).decode()
        # token_json nested
        tj = doc.get('token_json')
        if isinstance(tj, dict):
            tj_updates = {}
            for k in ('access_token', 'refresh_token'):
                v = tj.get(k)
                if v and not is_encrypted_value(v):
                    tj_updates[k] = fernet.encrypt(v.encode()).decode()
            if tj_updates:
                # merge into token_json
                merged = dict(tj)
                merged.update(tj_updates)
                updates['token_json'] = merged

        if updates:
            try:
                res = coll.update_one({'_id': _id}, {'$set': updates}, upsert=False)
                if getattr(res, 'modified_count', 0) > 0:
                    total_updated += 1
                    sample_ids.append(_id)
                else:
                    total_skipped += 1
            except PyMongoError:
                # retry once
                try:
                    res = coll.update_one({'_id': _id}, {'$set': updates}, upsert=False)
                    if getattr(res, 'modified_count', 0) > 0:
                        total_updated += 1
                        sample_ids.append(_id)
                    else:
                        total_skipped += 1
                except Exception:
                    total_skipped += 1
        else:
            total_skipped += 1

    duration = time.time() - start
    return {
        'scanned': total_scanned,
        'updated': total_updated,
        'skipped': total_skipped,
        'duration_seconds': duration,
        'sample_ids': sample_ids[:10],
    }


def post_check(db, fernet, sample_ids: List[Any], sample_size=5):
    coll = db.platform_tokens
    samples = random.sample(sample_ids, min(len(sample_ids), sample_size)) if sample_ids else []
    ok = 0
    details = []
    for _id in samples:
        doc = coll.find_one({'_id': _id})
        try:
            at = doc.get('access_token')
            if at:
                fernet.decrypt(at.encode())
            rt = doc.get('refresh_token')
            if rt:
                fernet.decrypt(rt.encode())
            details.append({'_id': _id, 'ok': True})
            ok += 1
        except Exception as e:
            details.append({'_id': _id, 'ok': False, 'error': str(e)})
    return {'checked': len(samples), 'ok': ok, 'details': details}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    db = connect_db()
    coll = db.platform_tokens

    print('Starting migration script', datetime.utcnow().isoformat())
    fernet = get_fernet()

    # Dry-run: count candidates
    cursor = find_candidates(coll, batch_size=1)
    candidates_count = coll.count_documents({'$or': [
        {'access_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
        {'refresh_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
        {'token_json.access_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
        {'token_json.refresh_token': {'$exists': True, '$ne': None, '$not': {'$regex': '^gAAAA'}}},
    ]})
    total_docs = coll.count_documents({})
    print(f'total_docs={total_docs}, candidates={candidates_count}')

    if args.dry_run and not args.apply:
        print('Dry-run only. Exiting.')
        return

    # Backup
    print('Creating backup of platform_tokens...')
    dst, backup_count = backup_collection(db, src='platform_tokens')
    print(f'Backup collection: {dst} ({backup_count} documents)')

    # Apply migration
    print('Applying migration...')
    result = migrate(db, fernet, batch_size=500)
    print('Migration result:', json.dumps(result, default=str))

    # Post-check
    post = post_check(db, fernet, result.get('sample_ids', []), sample_size=5)
    print('Post-check:', json.dumps(post, default=str))


if __name__ == '__main__':
    main()
