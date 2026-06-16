# Contributing to OpenLedger

Thanks for your interest in contributing.

## Development setup

```bash
git clone https://github.com/Attri-Inc/open-ledger.git
cd open-ledger
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python scripts/seed.py        # creates ./data/openledger.db with sample books
```

## Running the MCP server

```bash
python run_mcp.py             # stdio (default — for Claude Desktop / Code)
MCP_TRANSPORT=sse python run_mcp.py
```

## Running the checks

```bash
python scripts/smoke_test.py  # exercises every tool + asserts invariants
pytest                        # unit/integration tests
```

## Linting

```bash
ruff check .
ruff format .
```

## Pull request guidelines

- One logical change per PR. Refactors and feature work go in separate PRs.
- Add or update tests for behavioural changes.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Keep public tool/schema additions documented in `README.md` and `docs/`.
- Never weaken a core invariant (balanced transactions, immutable postings,
  same-transaction audit rows) without a documented rationale and tests.

## Reporting bugs

Open an issue with:
- OpenLedger version
- Python version
- Reproduction steps
- Expected vs actual behaviour

## Reporting security issues

See [SECURITY.md](SECURITY.md). Do not open a public issue for vulnerabilities.

## Code of conduct

Be excellent to each other.
