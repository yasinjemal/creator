#!/usr/bin/env python3
"""List recent migration audits from MongoDB.

Usage:
  python list_migration_audits.py --limit 10 --pretty

Defaults to MONGO_URI env var or mongodb://mongo:27017/creatorflow
"""
import os
import json
import argparse
from pymongo import MongoClient
from datetime import datetime


def connect_db():
    uri = os.getenv('MONGO_URI', 'mongodb://mongo:27017/creatorflow')
    client = MongoClient(uri)
    return client.get_default_database()


def format_doc(doc):
    # Convert ObjectId and datetime to strings for JSON
    out = dict(doc)
    if '_id' in out:
        out['_id'] = str(out['_id'])
    if 'timestamp' in out:
        try:
            # ensure isoformat
            out['timestamp'] = out['timestamp']
        except Exception:
            out['timestamp'] = str(out['timestamp'])
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=10, help='Number of recent audits to list')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON')
    args = parser.parse_args()

    db = connect_db()
    coll = db.get_collection('migration_audits')
    cursor = coll.find({}).sort('timestamp', -1).limit(args.limit)
    docs = [format_doc(d) for d in cursor]
    if args.pretty:
        print(json.dumps(docs, indent=2, sort_keys=True))
    else:
        print(json.dumps(docs))


if __name__ == '__main__':
    main()
