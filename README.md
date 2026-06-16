# OpenLedger

**Local-first double-entry accounting, queryable by humans and agents.**

SQLite-backed ledger. MCP server with 15 tools. Immutable transactions,
contra-posting corrections, append-only audit log.

Sibling services: [open-crm](../../open-crm) (memory) · [openwatch](../../openwatch) (observability) · **openledger (money)**

---

## Quick Start

```bash
cd open-ledger
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/seed.py            # bootstrap a fresh dev DB with sample books
```

### Connect from Claude Desktop / Code

```bash
python run_mcp.py                 # stdio transport (default)
```

For Claude Code:
```bash
claude mcp add openledger -s user -- \
  /absolute/path/to/open-ledger/.venv/bin/python \
  /absolute/path/to/open-ledger/run_mcp.py
```

See [docs/claude-connector.md](docs/claude-connector.md) for the full setup.

---

## Architecture

```
                ┌─────────────────────────────────────┐
                │          SQLite ledger              │
                │  accounts · transactions ·          │
                │  entry_lines · audit_log · settings │
                └──────────────────┬──────────────────┘
                                   │
                                   ▼
                         MCP server (stdio / SSE :8791)
                         15 tools — reads + safe writes
                                   │
                                   ▼
                         Claude Desktop, Claude Code,
                         agent frameworks
```

### Core invariants

1. Every transaction has ≥ 2 entry lines and `sum(debits) == sum(credits)` — enforced
   in the write path inside one DB transaction.
2. All amounts are **integer minor units (cents)**. No floats anywhere.
3. Transactions and entry lines are **immutable**. Corrections happen via
   `reverse_transaction` (contra posting), never UPDATE/DELETE.
4. Every mutation writes an audit-log row **in the same DB transaction**.

### MCP tools (15)

| Group | Tools |
|---|---|
| Accounts | `list_accounts` · `get_account` · `get_balance` · `get_account_ledger` · `create_account` |
| Journal | `get_transaction` · `search_transactions` · `post_transaction` · `transfer_funds` · `reverse_transaction` |
| Reports | `get_trial_balance` · `get_profit_loss` · `get_balance_sheet` |
| Audit | `get_audit_log` |
| Escape hatch | `run_query` (SQL `SELECT` only) |

### Configuration

| Env var | Default | Notes |
|---|---|---|
| `OPENLEDGER_DB` | `./data/openledger.db` | SQLite path |
| `MCP_TRANSPORT` | `stdio` (via `run_mcp.py`) | `stdio` or `sse` |
| `MCP_PORT` | `8791` | SSE only |

---

## Example questions to ask Claude

- "How much cash do we have right now?"
- "Show me the P&L for January."
- "Are the books balanced?" (trial balance)
- "Post a $250 cash sale for today."
- "Move $500 from Wallet A to Wallet B."
- "What was reversed recently, and why?"
