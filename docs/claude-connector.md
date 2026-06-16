# Claude Connector Setup (MCP)

## 1) Install dependencies

```bash
cd /Users/sahilkhirsaria/Desktop/Workspace/Project/open-ledger
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Seed the database

```bash
python scripts/seed.py
```

This creates `data/openledger.db` with 10 accounts, ~25 transactions
(including one reversal), and an audit trail. Re-running it resets the DB.

## 3a) Connect to Claude Code (recommended)

```bash
claude mcp add openledger -s user -- \
  /Users/sahilkhirsaria/Desktop/Workspace/Project/open-ledger/.venv/bin/python \
  /Users/sahilkhirsaria/Desktop/Workspace/Project/open-ledger/run_mcp.py
```

Then restart Claude Code (or run `/mcp` to check status).

## 3b) Connect to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "openledger": {
      "command": "/Users/sahilkhirsaria/Desktop/Workspace/Project/open-ledger/.venv/bin/python",
      "args": [
        "/Users/sahilkhirsaria/Desktop/Workspace/Project/open-ledger/run_mcp.py"
      ],
      "env": {
        "OPENLEDGER_DB": "/Users/sahilkhirsaria/Desktop/Workspace/Project/open-ledger/data/openledger.db"
      }
    }
  }
}
```

Then fully quit and reopen Claude Desktop (Cmd+Q, not just close the window).

> **Why the `.venv` python?** The `mcp` package is installed inside the
> virtualenv. Pointing the config at the system `python3` would fail with
> `ModuleNotFoundError: mcp`.

## 4) Verify tools

In Claude, you should see 15 tools named `list_accounts`, `get_balance`,
`get_trial_balance`, `post_transaction`, `run_query`, etc.

Try asking:

- "How much is in the Bank account?"
- "Show me the trial balance — are the books balanced?"
- "What did we spend on rent this year?"

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server shows "failed" in Claude | Check the python path is the `.venv` one; run `run_mcp.py` manually to see the error |
| Tools return "no such table" | Run `python scripts/seed.py` first |
| `ModuleNotFoundError: mcp` | `pip install -r requirements.txt` inside the venv |
