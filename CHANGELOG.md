# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-06-16

### Added
- MCP server (`src/mcp_server.py`) exposing 15 tools over stdio or SSE:
  account, balance, ledger, transaction, report (trial balance, profit &
  loss, balance sheet), and audit reads, plus safe write tools
  (`create_account`, `post_transaction`, `transfer_funds`,
  `reverse_transaction`) and a `run_query` SELECT-only escape hatch.
- SQLite double-entry warehouse: `accounts`, `transactions`, `entry_lines`,
  `audit_log`, `org_settings`. All money is stored as integer minor units.
- Core invariants enforced in the write path: balanced transactions
  (debits == credits, ≥ 2 lines), immutable postings, contra-posting
  reversals, and an audit row written in the same DB transaction as every
  mutation.
- `scripts/seed.py` bootstraps a fresh dev database with the chart of
  accounts and transactions from the `open-ledger.html` demo plus recent
  monthly activity; it verifies the seeded books balance and fails loudly
  otherwise. `scripts/schema.sql` ships the canonical table definitions.
- `scripts/smoke_test.py` exercises every MCP tool and asserts the
  accounting invariants against the seeded database.
- Dockerfile (non-root) + docker-compose (localhost-bound) for local runs.
- `docs/claude-connector.md` — Claude Desktop / Code setup guide.
- `pyproject.toml` packaging.

[Unreleased]: https://github.com/Attri-Inc/open-ledger/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Attri-Inc/open-ledger/releases/tag/v0.1.0
