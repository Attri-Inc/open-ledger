# Contributing to OpenLedger

Thanks for your interest in contributing.

## Development setup

```bash
git clone https://github.com/Attri-Inc/open-ledger.git
cd open-ledger
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python scripts/seed.py        # creates ./data/openledger.db with sample books
```

Configuration is read from environment variables (see `.env.example` for the
list, e.g. `OPENLEDGER_DB`). There is no automatic `.env` loading — export the
variables in your shell if you want to override the defaults.

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

## Linting & types

```bash
ruff check .
ruff format --check .
mypy . --ignore-missing-imports
```

These are the same checks CI runs — run them before pushing.

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

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating, you agree to uphold it.
