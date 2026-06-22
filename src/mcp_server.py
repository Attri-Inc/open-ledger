"""OpenLedger MCP Server — 15 tools for double-entry accounting.

This module is a thin transport adapter: each tool holds no business logic — it
calls a service (resolved from the composition root) and maps the result (or a
typed DomainError) to a JSON envelope via the serialization helpers.
"""

import os

from mcp.server.fastmcp import FastMCP

from src.config import MCP_PORT
from src.container import container
from src.domain.errors import DomainError
from src.serialization import error_response, tool_response

mcp = FastMCP(
    "openledger",
    instructions="""
OpenLedger is a local-first double-entry accounting system.
It provides tools to query the chart of accounts, balances, ledgers, transactions,
and financial reports (trial balance, profit & loss, balance sheet), plus safe
write tools to post balanced transactions, transfer funds, and reverse mistakes.
All amounts are integer minor units (cents): 100 = $1.00.
Transactions are immutable — corrections happen via reverse_transaction.
""",
)


# ---------------------------------------------------------------------------
# Accounts & balances (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_accounts(
    account_type: str | None = None, include_archived: bool = False, q: str | None = None
) -> str:
    """List the chart of accounts with current balances.
    Filter by type (asset, liability, equity, income, expense) or search by name/code.
    Use for "what accounts do we have?", "show all expense accounts"."""
    return tool_response(await container.accounts.list_accounts(account_type, include_archived, q))


@mcp.tool()
async def get_account(account: str) -> str:
    """Get one account by id, code (e.g. "1010"), or name (e.g. "Bank").
    Use for "tell me about the Bank account"."""
    result = await container.accounts.with_balance(account)
    if not result:
        return error_response(f"Account not found: {account}")
    return tool_response(result)


@mcp.tool()
async def get_balance(account: str, as_of: str | None = None) -> str:
    """Get an account's balance, optionally as of a date (YYYY-MM-DD).
    Balance is positive on the account's normal side.
    Use for "how much cash do we have?", "Bank balance at end of January?"."""
    result = await container.accounts.balance(account, as_of)
    if not result:
        return error_response(f"Account not found: {account}")
    return tool_response(result)


@mcp.tool()
async def get_account_ledger(
    account: str, date_from: str | None = None, date_to: str | None = None, limit: int = 100
) -> str:
    """Get an account's ledger: every entry line with a running balance.
    Use for "show me all Bank activity", "Wallet A history in January"."""
    result = await container.accounts.ledger(account, date_from, date_to, limit)
    if not result:
        return error_response(f"Account not found: {account}")
    return tool_response(result)


# ---------------------------------------------------------------------------
# Transactions (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_transaction(transaction_id: str) -> str:
    """Get a transaction with all its entry lines.
    Use for "show me transaction txn_abc123"."""
    result = await container.ledger.get_transaction(transaction_id)
    if not result:
        return error_response(f"Transaction not found: {transaction_id}")
    return tool_response(result)


@mcp.tool()
async def search_transactions(
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> str:
    """Search the journal. Filter by text (description/reference), date range,
    account (id/code/name), or status (posted, reversed).
    Use for "show January transactions", "find the payroll entries"."""
    return tool_response(
        await container.ledger.search(q, date_from, date_to, account, status, limit, offset)
    )


# ---------------------------------------------------------------------------
# Reports (read)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_trial_balance(as_of: str | None = None) -> str:
    """Trial balance: every account's debit/credit balance. Totals must match.
    Use for "are the books balanced?", "trial balance as of March 31"."""
    return tool_response(await container.reports.trial_balance(as_of))


@mcp.tool()
async def get_profit_loss(date_from: str | None = None, date_to: str | None = None) -> str:
    """Profit & loss: income minus expenses over a period.
    Use for "did we make money in January?", "P&L year to date"."""
    return tool_response(await container.reports.profit_loss(date_from, date_to))


@mcp.tool()
async def get_balance_sheet(as_of: str | None = None) -> str:
    """Balance sheet: assets = liabilities + equity (incl. current earnings).
    Use for "what's our financial position?"."""
    return tool_response(await container.reports.balance_sheet(as_of))


@mcp.tool()
async def get_audit_log(
    action: str | None = None, actor: str | None = None, limit: int = 25, offset: int = 0
) -> str:
    """Read the append-only audit log of every mutation.
    Actions: create_account, post_transaction, transfer_funds, reverse_transaction, seed.
    Use for "who did what?", "show recent activity"."""
    return tool_response(await container.audit.list(action, actor, limit, offset))


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_account(
    code: str, name: str, account_type: str, description: str | None = None
) -> str:
    """Create a new account in the chart of accounts.
    account_type: asset, liability, equity, income, or expense.
    The normal side (debit/credit) is derived from the type.
    Use for "add an Office Supplies expense account with code 5200"."""
    try:
        return tool_response(
            await container.accounts.create(code, name, account_type, description, actor="mcp")
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def post_transaction(
    txn_date: str, description: str, lines: list[dict], reference: str | None = None
) -> str:
    """Post a balanced journal transaction (immutable once posted).
    txn_date: YYYY-MM-DD. lines: at least 2 of
    {"account": "<id|code|name>", "direction": "debit"|"credit", "amount_minor": <cents>, "memo": "..."}.
    Sum of debits must equal sum of credits. amount_minor is integer cents (100 = $1.00).
    Example — a $250.00 cash sale:
    [{"account": "Cash", "direction": "debit", "amount_minor": 25000},
     {"account": "Sales Revenue", "direction": "credit", "amount_minor": 25000}]"""
    try:
        return tool_response(
            await container.ledger.post(txn_date, description, lines, reference, actor="mcp")
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def transfer_funds(
    from_account: str, to_account: str, amount_minor: int, txn_date: str, memo: str | None = None
) -> str:
    """Transfer money between two accounts (convenience: builds a balanced 2-line transaction).
    amount_minor is integer cents. Use for "move $500 from Wallet A to Wallet B"."""
    try:
        return tool_response(
            await container.ledger.transfer(
                from_account, to_account, amount_minor, txn_date, memo, actor="mcp"
            )
        )
    except DomainError as e:
        return error_response(str(e))


@mcp.tool()
async def reverse_transaction(transaction_id: str, reason: str) -> str:
    """Reverse a posted transaction via a contra posting (flips every line).
    The original is preserved and marked 'reversed' — nothing is ever deleted.
    Use for "undo that duplicate rent payment"."""
    try:
        return tool_response(await container.ledger.reverse(transaction_id, reason, actor="mcp"))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Raw query
# ---------------------------------------------------------------------------


@mcp.tool()
async def run_query(sql: str) -> str:
    """Run a read-only SQL SELECT against the OpenLedger database.
    Tables: accounts, transactions, entry_lines, audit_log, org_settings.
    Only SELECT is allowed — no mutations.
    Use as an escape hatch when other tools don't cover the question."""
    try:
        return tool_response(await container.queries.run(sql))
    except DomainError as e:
        return error_response(str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Console entry point. Honours MCP_TRANSPORT (stdio default, or sse)."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")  # "stdio" or "sse"
    if transport == "sse":
        os.environ.setdefault("FASTMCP_PORT", str(MCP_PORT))
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
