# Security Policy

## Supported versions

OpenLedger is in early development. Only the latest minor release receives
security fixes.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✓         |

## Reporting a vulnerability

Please report security vulnerabilities privately — either via GitHub's
**Security → Report a vulnerability** (private advisory) on this repository, or
by email to **engineering@attri.ai**.

Include:
- A description of the issue
- Steps to reproduce
- Affected version(s)
- Impact assessment if you have one

Please do not file public GitHub issues for security vulnerabilities.

## Disclosure

We follow a coordinated disclosure model. Once a fix is available we will:
1. Release a patched version.
2. Publish a GitHub Security Advisory crediting the reporter (unless they
   prefer to remain anonymous).
3. Update the changelog with the CVE identifier when one has been assigned.

## Hardening notes for operators

- The `run_query` tool is read-only by construction: it runs on a dedicated
  connection opened with `PRAGMA query_only=ON` (the engine rejects any write),
  and additionally requires the statement to start with `SELECT`/`WITH` and
  rejects write keywords as a second line of defence. It still permits
  arbitrary **read** access to the ledger — run OpenLedger behind
  authentication if the data contains anything sensitive.
- The write tools (`create_account`, `post_transaction`, `transfer_funds`,
  `reverse_transaction`) mutate the ledger. Expose them only to trusted
  agents/clients. Postings are immutable and every mutation is audited, so
  changes are traceable — but they are not access-controlled at the tool
  layer in v0.1.
- When running over SSE, bind to `127.0.0.1` (the default in
  `docker-compose.yml`). Do not publish the port to the LAN.
- The SQLite database file should have filesystem permissions restricted to
  the OpenLedger process user.
