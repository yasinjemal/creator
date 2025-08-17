import os
from datetime import datetime
from pymongo import MongoClient

client = MongoClient(os.getenv('MONGO_URI','mongodb://mongo:27017/creatorflow'))
db = client.get_default_database()

audit = {
    'migration': 'encrypt_platform_tokens',
    'script': 'scripts/migrate_encrypt_tokens.py',
    'timestamp': datetime.utcnow().isoformat() + 'Z',
    'total_docs': 3,
    'candidates': 2,
    'updated': 2,
    'skipped': 0,
    'duration_seconds': 0.03607630729675293,
    'backup_collection': 'platform_tokens_backup_20250817T140556Z',
    'sample_ids': ['68a1c517e51de1ae3a4895fe', '68a1c6f8e51de1ae3a48965c'],
    'post_check': {'checked': 2, 'ok': 2},
    'notes': 'Executed inside backend container with --apply'
}
res = db.migration_audits.insert_one(audit)
print('inserted_id', str(res.inserted_id))
