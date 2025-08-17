Migration README
=================

This folder contains `migrate_encrypt_tokens.py`, a script used to migrate plaintext OAuth tokens
stored in the `platform_tokens` collection to Fernet-encrypted values.

Summary of the migration just performed
- Script: `migrate_encrypt_tokens.py`
- Backup collection created: `platform_tokens_backup_20250817T140556Z`
- Total documents in `platform_tokens` before migration: 3
- Candidate documents (plaintext tokens): 2
- Documents updated (encrypted): 2
- Post-check random decrypts OK: 2/2

How the script works (short)
- Dry-run mode (`--dry-run`) counts candidates and prints a summary without changing data.
- Apply mode (`--apply`) will:
  - Create a backup collection named `platform_tokens_backup_{timestamp}` (UTC).
  - Scan `platform_tokens` and encrypt the following fields where they are not already Fernet-encrypted (Fernet strings begin with `gAAAA`):
    - `access_token`
    - `refresh_token`
    - `token_json.access_token`
    - `token_json.refresh_token`
  - Updates are performed with `WriteConcern(w='majority')` and a single retry on write failure.
  - Batching is implemented via the cursor; batch_size ~= 500.
  - A post-check decrypts a small random sample of updated rows to ensure encryption succeeded.

Reverting from backup
- To revert the migration, you can restore the backup collection in Mongo:

  1. Drop the current `platform_tokens` (or rename it):
     - `db.platform_tokens.renameCollection('platform_tokens_pre_migration')` or `db.platform_tokens.drop()` after export.
  2. Rename the backup into place:
     - `db.platform_tokens_backup_20250817T140556Z.renameCollection('platform_tokens')`

Exporting the backup
- To export the backup collection to an external file (recommended for long-term retention):
  - Use `mongodump`:
    - `mongodump --uri="$MONGO_URI" --collection=platform_tokens_backup_20250817T140556Z --out=./mongo_backups`

Security & notes
- The migration encrypts tokens with the Fernet key provided via Docker secrets (mounted at `/run/secrets/encryption_key`) or `ENCRYPTION_KEY` env var.
- The backup collection remains in the same MongoDB instance; if you need an off-host backup, run `mongodump` as above.
- For production, consider using a central key manager (Vault/KMS) and implement key rotation.

Next steps you may want
- Rotate the Fernet key and re-encrypt all tokens with a new key (the repo can be extended with a key-rotation script).
- Integrate Vault / cloud KMS for secret management.
- Remove the backup collection after a retention window and after verifying application behavior.
