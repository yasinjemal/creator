#!/usr/bin/env python3
"""Cleanup migration backup collections.

This script finds collections named like `platform_tokens_backup_{timestamp}` and either
lists or drops those older than a retention period.

Usage:
  python cleanup_migration_backups.py --dry-run --days 30
  python cleanup_migration_backups.py --apply --days 30
  python cleanup_migration_backups.py --keep 3  # keep newest 3 backups

Safety guards:
 - Default is --dry-run (no destructive action).
 - Requires --apply to actually drop collections.
 - Will print summary and examples before dropping.
"""
from __future__ import annotations
import os
import re
import argparse
from datetime import datetime
from pymongo import MongoClient

BACKUP_PATTERN = re.compile(r'^platform_tokens_backup_(\d{8}T\d{6}Z)$')


def connect_db():
    uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017/creatorflow')
    client = MongoClient(uri)
    return client.get_default_database()


def parse_ts(ts_str: str) -> datetime:
    return datetime.strptime(ts_str, '%Y%m%dT%H%M%SZ')


def find_backup_collections(db):
    names = db.list_collection_names()
    backups = []
    for n in names:
        m = BACKUP_PATTERN.match(n)
        if m:
            ts = m.group(1)
            try:
                dt = parse_ts(ts)
                backups.append((n, dt))
            except Exception:
                continue
    backups.sort(key=lambda x: x[1], reverse=True)  # newest first
    return backups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', default=True, help='Show what would be removed')
    parser.add_argument('--apply', action='store_true', help='Actually drop matching collections')
    parser.add_argument('--days', type=int, default=30, help='Retention days; backups older than this will be removed')
    parser.add_argument('--keep', type=int, default=0, help='Keep the N most recent backups (overrides days if >0)')
    args = parser.parse_args()

    # If user passed --apply, disable default dry-run
    if args.apply:
        args.dry_run = False

    db = connect_db()
    backups = find_backup_collections(db)
    now = datetime.utcnow()

    to_remove = []
    if args.keep and args.keep > 0:
        # keep newest args.keep
        to_remove = backups[args.keep:]
    else:
        for name, ts in backups:
            age_days = (now - ts).days
            if age_days >= args.days:
                to_remove.append((name, ts))

    print(f'found {len(backups)} backup(s); candidates for removal: {len(to_remove)}')
    if to_remove:
        for name, ts in to_remove:
            print(f'  - {name}  (timestamp={ts.isoformat()} UTC)')
    else:
        print('  (none)')

    if args.dry_run:
        print('\nDry-run mode: no collections were dropped. Run with --apply to remove.')
        return

    # confirm before destructive action
    print('\nApplying removal of the above collections...')
    for name, ts in to_remove:
        print('Dropping', name)
        try:
            db.drop_collection(name)
        except Exception as e:
            print('  failed:', e)
    print('Done.')


if __name__ == '__main__':
    main()
