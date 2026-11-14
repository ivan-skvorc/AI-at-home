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

## The CAD module's script interpreter (fork feature)

The optional CAD extension (`examples/deerflow-extension-cad`, FORK.md §51) takes
a CadQuery script written by a language model. Model text is untrusted input,
and the default install gives the agent no shell on purpose, so the extension
does not run the script. Its interpreter is a security boundary and is described
here as one.

- **The script is read, never executed.** It is parsed into a syntax tree. A
  whitelist of node types is checked before anything is evaluated; every other
  construct is refused with its line: imports other than `import cadquery as cq`,
  attribute access, any call other than `cq.Workplane(...)` and an allow-listed
  method, definitions, loops, branches, comprehensions, f-strings, subscripts.
  `exec`, `eval` and `compile` never receive script text.
- **The allow-list is data** (`allowlist.py`): method names with the kind of
  each argument. A method that takes a file path, a callable, a font or a raw
  kernel object is not on it. The one attribute lookup a script can cause is for
  a name that is a key of that table.
- **Reading and building happen in a child process**, started in isolated mode
  in an empty temporary directory with an environment that carries no Gateway
  credentials. The Gateway process neither parses the script nor loads the
  geometry kernel. The parent enforces a wall clock and kills the process group;
  the child sets memory, CPU and file-size limits where the operating system
  offers them.
- **Resource use is bounded before the kernel starts**: script size, syntax
  nodes, nesting, number magnitude, exponent size and pattern instances.
- **The kept script reads the way it was read.** Control characters and
  invisible Unicode (zero-width characters, direction overrides, line
  separators) are refused anywhere in the text, so a statement cannot hide from
  a person who opens the `.py` file beside the part.

What it is not: a sandbox for the geometry kernel. A defect in the kernel that
an allow-listed operation can reach is contained by the child process and its
limits, not by the interpreter. The extension is operator-installed code like
any other and runs with Gateway privileges; its files are written through the
host's bounded writer (`ToolContext.write_output`), into the calling
conversation only.

A change that widens the allow-list, adds a string parameter, or lets any value
from a script reach `getattr`, a file path or a subprocess argument is a change
to this boundary and needs its own review. `tests/test_interpreter.py` in the
package holds the refused constructs; a new one belongs there.
