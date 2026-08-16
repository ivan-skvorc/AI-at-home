# Security Policy

## Supported Versions

As deer-flow doesn't provide an official release yet, please use the latest version to receive security updates.
Currently, we have two branches to maintain:
* main branch for deer-flow 2.x
* main-1.x branch for deer-flow 1.x

## Reporting a Vulnerability

Please go to https://github.com/bytedance/deer-flow/security to report the vulnerability you find.

## Backups and credentials (fork feature)

`make backup` snapshots a whole instance into a single archive. Because that
archive leaves the machine — onto a USB stick, another host, a cloud drive — it
is treated as a potential credential-exposure path rather than as plain data:

- **Credentials are excluded by default.** `.env` (API keys) and the per-user
  integration credentials under `users/{user_id}/integrations/` (app secrets,
  OAuth tokens) are stored `0600`/`0700` on disk and are **not** written into a
  backup unless `--include-secrets` / `INCLUDE_SECRETS=1` is passed explicitly.
- **A secret-bearing archive is owner-only.** It is created mode `0600` at open
  time, not chmod'ed after the fact, so it is never briefly world-readable while
  being written. Treat such an archive exactly like the key file it contains:
  do not attach it to an issue, a support bundle, or a shared drive, and prefer
  an encrypted destination. `python3 scripts/backup.py inspect <archive>` reports
  whether a given archive carries credentials.
- **Restoring a credential-free archive does not remove existing credentials**
  on the target machine — it restores what it carries and leaves the rest alone.
- **File permissions are preserved on restore**, so credential directories come
  back `0700` rather than being widened by the round trip. Ownership is not
  restored (that would require root); restore as the user who should own the
  files.

For redacted diagnostics intended for sharing, use `make support-bundle`, which
is built for that purpose — not a backup archive.
