"""Smoke test — exercises every MCP tool against the seeded database.

Calls each tool function through the FastMCP server's registry, validates
invariants (trial balance nets to zero, balance sheet equation holds,
unbalanced transactions rejected, reversal round-trips), and prints proof.

Usage: .venv/bin/python scripts/smoke_test.py
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.mcp_server import mcp  # noqa: E402

PASS, FAIL = "✓", "✗"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    print(f"  {PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


async def call(tool: str, **kwargs) -> dict | list:
    """Invoke a registered MCP tool by name, exactly as Claude would."""
    result = await mcp.call_tool(tool, kwargs)
    # FastMCP returns (content_list, ...) as a tuple; first content item is TextContent.
    block = result[0][0] if isinstance(result, tuple) else result[0]  # type: ignore[index]
    return json.loads(block.text)  # type: ignore[union-attr]


async def main():
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    print("1. Tool registry")
    tools = await mcp.list_tools()
    names = sorted(t.name for t in tools)
    check("15 tools registered", len(tools) == 15, ", ".join(names))

    print("2. Read tools")
    accounts = await call("list_accounts")
    check("list_accounts", len(accounts) == 10, f"{len(accounts)} accounts")

    bank = await call("get_account", account="Bank")
    check(
        "get_account (by name)", bank.get("code") == "1010", f"Bank balance {bank.get('balance')}"
    )

    bal = await call("get_balance", account="1010")
    check("get_balance (by code)", "balance_minor" in bal, f"{bal['name']}: {bal['balance']}")

    ledger = await call("get_account_ledger", account="Wallet A")
    check(
        "get_account_ledger",
        len(ledger["entries"]) >= 3,
        f"{len(ledger['entries'])} entries, ending {ledger['ending_balance']}",
    )

    found = await call("search_transactions", q="rent")
    check("search_transactions", found["total"] >= 5, f"{found['total']} rent transactions")

    txn = await call("get_transaction", transaction_id=found["items"][0]["id"])
    check("get_transaction", len(txn["lines"]) >= 2, f"{txn['description']} · {txn['total']}")

    tb = await call("get_trial_balance")
    check(
        "get_trial_balance BALANCED",
        tb["balanced"] and tb["total_debit_minor"] == tb["total_credit_minor"],
        f"debits {tb['total_debit']} == credits {tb['total_credit']}",
    )

    pl = await call("get_profit_loss", date_from="2026-01-01", date_to="2026-01-31")
    check(
        "get_profit_loss (January)",
        pl["total_income_minor"] == 400_000,
        f"income {pl['total_income']}, expenses {pl['total_expenses']}, net {pl['net_profit']}",
    )

    bs = await call("get_balance_sheet")
    check(
        "get_balance_sheet EQUATION",
        bs["equation_holds"],
        f"assets {bs['total_assets']} == liabilities {bs['total_liabilities']} + equity {bs['total_equity']}",
    )

    audit = await call("get_audit_log", limit=5)
    check("get_audit_log", audit["total"] >= 27, f"{audit['total']} audit rows")

    rq = await call("run_query", sql="SELECT COUNT(*) AS n FROM transactions")
    check("run_query (SELECT)", rq[0]["n"] >= 26, f"{rq[0]['n']} transactions")

    blocked = await call("run_query", sql="DELETE FROM transactions")
    check("run_query blocks mutations", "error" in blocked, blocked.get("error", ""))

    print("3. Write tools")
    acct = await call(
        "create_account",
        code="5200",
        name="Office Supplies",
        account_type="expense",
        description="smoke test",
    )
    check("create_account", acct.get("normal_side") == "debit", f"{acct['code']} · {acct['name']}")

    bad = await call(
        "post_transaction",
        txn_date=today,
        description="unbalanced test",
        lines=[
            {"account": "Cash", "direction": "debit", "amount_minor": 100},
            {"account": "Sales Revenue", "direction": "credit", "amount_minor": 999},
        ],
    )
    check("post_transaction REJECTS unbalanced", "error" in bad, bad.get("error", ""))

    posted = await call(
        "post_transaction",
        txn_date=today,
        description="Bought office supplies (smoke test)",
        reference="TEST",
        lines=[
            {"account": "Office Supplies", "direction": "debit", "amount_minor": 4_500},
            {"account": "Cash", "direction": "credit", "amount_minor": 4_500},
        ],
    )
    check(
        "post_transaction (balanced)",
        posted.get("status") == "posted",
        f"{posted['id']} · {posted['total']}",
    )

    moved = await call(
        "transfer_funds",
        from_account="Wallet B",
        to_account="Wallet A",
        amount_minor=10_000,
        txn_date=today,
        memo="smoke test",
    )
    check(
        "transfer_funds",
        moved.get("status") == "posted",
        f"{moved['description']} · {moved['total']}",
    )

    contra = await call(
        "reverse_transaction", transaction_id=posted["id"], reason="smoke test cleanup"
    )
    original = await call("get_transaction", transaction_id=posted["id"])
    check(
        "reverse_transaction",
        original["status"] == "reversed" and contra["reverses_id"] == posted["id"],
        f"contra {contra['id']} flips {posted['id']}",
    )

    double = await call("reverse_transaction", transaction_id=posted["id"], reason="again")
    check("reverse REJECTS double-reversal", "error" in double, double.get("error", ""))

    print("4. Post-write invariants")
    tb2 = await call("get_trial_balance")
    check(
        "trial balance STILL balanced after writes",
        tb2["balanced"],
        f"debits {tb2['total_debit']} == credits {tb2['total_credit']}",
    )
    supplies = await call("get_balance", account="Office Supplies")
    check(
        "reversal restored balance",
        supplies["balance_minor"] == 0,
        f"Office Supplies back to {supplies['balance']}",
    )

    await db.close_db()
    print()
    if failures:
        print(f"{FAIL} {len(failures)} FAILED: {failures}")
        sys.exit(1)
    print(f"{PASS} ALL CHECKS PASSED — every tool verified against the seeded SQLite database")


if __name__ == "__main__":
    asyncio.run(main())
