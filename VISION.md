# OpenLedger Vision

## The problem

Bookkeeping tools were built for humans clicking through forms. As agents
start to handle real operational work — recording sales, paying bills,
reconciling accounts — they need a system of record they can both *read*
and *write* with the same fidelity a human gets from an accounting UI, and
with guarantees a spreadsheet can't offer: every posting balanced, every
amount exact, every change traceable and reversible.

OpenLedger is that system of record.

## What OpenLedger is

A **local-first, double-entry accounting ledger** exposed through a Model
Context Protocol (MCP) server, so the books are queryable and mutable by
humans *and* by agents through the same tools.

The data model is deliberately small and classic:

- **`accounts`** — the chart of accounts (asset, liability, equity, income,
  expense), each with a normal side.
- **`transactions` + `entry_lines`** — immutable, balanced journal entries.
  Debits equal credits, always, enforced in the write path.
- **`audit_log`** — an append-only record of every mutation, written in the
  same database transaction as the change it describes.
- **`org_settings`** — the single-row organisation profile.

## Principles

1. **Correct by construction.** A transaction cannot be saved unless it has
   at least two lines and its debits equal its credits. Amounts are integer
   minor units (cents) — there is no float arithmetic anywhere.
2. **Immutable, not editable.** Postings are never updated or deleted.
   Corrections happen through `reverse_transaction`, a contra posting that
   preserves the original. The ledger is a ledger.
3. **Agent-callable from day one.** Every action a human can take is an MCP
   tool. Agents and people operate on the same books through the same rules.
4. **Auditable.** Every mutation writes an audit row atomically with the
   change. The audit trail can never be ahead of or behind the ledger.
5. **Local-first.** Ships as SQLite + a single Python process. Self-hosted,
   no data leaves the operator's machine.

## What OpenLedger is *not* (v0.1)

- Not multi-currency. One base currency per deployment; no FX conversion.
- Not a tax or invoicing engine. No AR/AP aging, no fiscal-period close.
- Not multi-tenant. Each deployment is a single set of books.
- Not a bank feed. Transactions are posted explicitly, not imported.

## Roadmap

### v0.1 (current)
MCP server (15 tools) over a SQLite double-entry ledger: chart of accounts,
balanced postings, transfers, reversals, per-account ledgers, and the three
core financial statements (trial balance, profit & loss, balance sheet),
all over an append-only audit log.

### v0.2
- REST API twin of every MCP tool (FastAPI, port 8790).
- API-key auth with read / write / admin roles; audit actor from the
  authenticated principal.
- Optimistic locking (`version`) on mutable rows; idempotency keys on writes.

### v0.3
- React + TypeScript frontend (mirroring the original single-file demo),
  consuming the REST API.
- Hash-chained, tamper-evident audit log with a `verify-audit-chain` command.

### v1.0
- Postgres backend option behind the same repository contracts.
- Fiscal periods and closing entries.
- Stable schema commitment.
