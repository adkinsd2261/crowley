# Crowley Disaster Recovery

Crowley's Git repository preserves code and documentation. Its live continuity
- memories, tickets, handoffs, project state, sparks, patterns, tasks, loops,
and decisions - lives in `crowley.db` and therefore requires a separate,
encrypted, off-device backup.

## Recovery target

Crowley uses:

- a consistent SQLite online snapshot;
- restic client-side encryption and deduplicated history;
- a private Cloudflare R2 bucket using its S3-compatible endpoint;
- hourly backups and a daily repository integrity check;
- isolated restore drills that never overwrite the live database;
- an R2 bucket lock on the restic `data/` prefix to retain encrypted pack data.

The R2 bucket is **not public** and is separate from the `api.javlin.ai`
Cloudflare Tunnel.

## What is backed up

- `crowley.db`, captured through SQLite's online backup API;
- processed Crowley handoffs as a redundant recovery trail;
- non-secret local state such as `brain.json`;
- a manifest containing SHA-256, SQLite integrity result, table counts, Git
  commit, machine metadata, and timestamp.

The backup deliberately excludes:

- `.env`;
- Cloudflare Tunnel credentials;
- local backup credentials.

Keep API keys in a password manager. Tunnel credentials can be reissued from
Cloudflare after a machine loss.

## The recovery key rule

The backup is useless without the restic repository password. Losing that
password makes the encrypted data irrecoverable.

Store these together in a password-manager recovery record:

1. R2 repository URL;
2. R2 Access Key ID;
3. R2 Secret Access Key;
4. restic repository password.

Keep one additional offline copy in a secure physical location. Do not store
the only copy on the Crowley computer, in the Crowley repository, or inside
the R2 bucket.

## One-time Cloudflare R2 setup

1. In Cloudflare, open **Storage & databases -> R2 -> Overview**.
2. Enable R2 if necessary.
3. Create a private bucket named `crowley-recovery`.
4. Under **Manage R2 API tokens**, create a token with:
   - **Object Read & Write**;
   - access to **only** `crowley-recovery`.
5. Copy the Access Key ID and Secret Access Key to the recovery record.
6. Note the account-specific endpoint:

   `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`

7. In the bucket's **Settings -> Bucket lock rules**, add:
   - name: `crowley-data-30d`;
   - prefix: `data/`;
   - retention: 30 days.

The lock protects encrypted restic data packs from deletion or overwrite for
30 days. Do not lock the `locks/` prefix; restic must create and remove its
short-lived repository locks.

## Configure this computer

Run from the repository root:

```powershell
venv\Scripts\python.exe scripts\crowley_backup.py configure
```

Use this repository URL:

```text
s3:https://<ACCOUNT_ID>.r2.cloudflarestorage.com/crowley-recovery
```

The credentials and repository password are sealed locally with Windows DPAPI.
That local sealed file cannot be decrypted on a replacement computer, which is
why the external recovery record is mandatory.

Initialize and make the first backup:

```powershell
venv\Scripts\python.exe scripts\crowley_backup.py init
venv\Scripts\python.exe scripts\crowley_backup.py backup --tag initial
venv\Scripts\python.exe scripts\crowley_backup.py check --read-data
venv\Scripts\python.exe scripts\crowley_backup.py drill
venv\Scripts\python.exe scripts\crowley_backup.py install-schedule
```

The schedule creates:

- `Crowley Encrypted Backup` - hourly;
- `Crowley Backup Integrity Check` - daily at 03:00.

On Windows, restore the existing named Cloudflare Tunnel at logon with:

```powershell
venv\Scripts\python.exe scripts\windows_bridge_task.py install
```

This uses `cloudflared/config.yml` and the existing credential file. It does
not create a new tunnel or hostname. If Task Scheduler requires administrator
permission, the installer uses the current user's Windows logon startup entry.

## Normal operation

```powershell
# Manual backup before risky work
venv\Scripts\python.exe scripts\crowley_backup.py backup --tag before-risk

# Show remote snapshots and schedule status
venv\Scripts\python.exe scripts\crowley_backup.py status

# Full integrity check
venv\Scripts\python.exe scripts\crowley_backup.py check --read-data

# Prove the latest snapshot can be restored
venv\Scripts\python.exe scripts\crowley_backup.py drill
```

Run a manual `before-risk` backup before deleting systems, migrating machines,
or making a destructive schema change.

## Recover on a replacement computer

1. Clone the Crowley repository.
2. Install Python, dependencies, and restic.
3. Retrieve the four recovery values from the password manager/offline copy.
4. Run `configure` with the existing repository URL and credentials.
5. Restore into an isolated directory:

```powershell
venv\Scripts\python.exe scripts\crowley_backup.py restore `
  --snapshot latest `
  --target C:\Crowley-Recovery
```

The command verifies the manifest SHA-256 and runs SQLite
`PRAGMA integrity_check`. It does **not** replace the live database.

After verification:

1. stop Crowley;
2. preserve any existing `crowley.db`;
3. copy the verified restored `crowley.db` into the repository root;
4. start Crowley;
5. run agent sync and confirm memory/ticket counts.

## Security properties and limits

- Restic encrypts data before it leaves the laptop.
- R2 credentials are scoped to one private bucket.
- R2 bucket lock limits deletion damage for encrypted data packs.
- Local automation secrets are DPAPI-sealed to the Windows user.
- Restore is isolated and hash/integrity checked.
- A compromised logged-in Windows account can still run backups or access
  locally decrypted credentials. Use BitLocker/device encryption, Windows
  Hello, and a strong account password.
- R2 is one off-device copy, not the external recovery key store. The
  password-manager/offline recovery record is a separate required control.

## Source

- Backup tooling: `scripts/crowley_backup.py`
- Local runtime state: `.crowley/backup/` (gitignored)
- Tests: `tests/test_crowley_backup.py`

## Official references

- [Restic: preparing a repository](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)
- [Restic: checking integrity and troubleshooting](https://restic.readthedocs.io/en/stable/077_troubleshooting.html)
- [Cloudflare R2: API tokens](https://developers.cloudflare.com/r2/api/tokens/)
- [Cloudflare R2: S3-compatible API](https://developers.cloudflare.com/r2/get-started/s3/)
- [Cloudflare R2: bucket lock rules](https://developers.cloudflare.com/r2/buckets/bucket-locks/)
