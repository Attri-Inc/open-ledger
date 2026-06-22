"""Tests for the core double-entry invariants, run against a seeded DB."""

import pytest

from src import db


async def test_chart_of_accounts_seeded():
    accounts = await db.list_accounts()
    assert len(accounts) == 10
    codes = {a["code"] for a in accounts}
    assert {"1000", "1010", "3000", "4000", "5100"} <= codes


async def test_seeded_books_balance():
    tb = await db.trial_balance()
    assert tb["balanced"]
    assert tb["total_debit_minor"] == tb["total_credit_minor"]


async def test_balance_sheet_equation_holds():
    bs = await db.balance_sheet()
    assert bs["equation_holds"]


async def test_balance_positive_on_normal_side():
    bank = await db.get_balance("Bank")
    assert bank is not None
    # Bank is an asset (normal side debit) and should be positive after seeding.
    assert bank["balance_minor"] > 0


async def test_post_unbalanced_is_rejected():
    with pytest.raises(ValueError, match="[Uu]nbalanced"):
        await db.post_transaction(
            "2026-06-01",
            "bad entry",
            [
                {"account": "Cash", "direction": "debit", "amount_minor": 100},
                {"account": "Sales Revenue", "direction": "credit", "amount_minor": 200},
            ],
        )


async def test_post_requires_two_lines():
    with pytest.raises(ValueError, match="at least 2"):
        await db.post_transaction(
            "2026-06-01",
            "single line",
            [{"account": "Cash", "direction": "debit", "amount_minor": 100}],
        )


async def test_post_then_reverse_restores_balance_and_is_immutable():
    txn = await db.post_transaction(
        "2026-06-02",
        "office supplies (test)",
        [
            {"account": "Rent Expense", "direction": "debit", "amount_minor": 5_000},
            {"account": "Cash", "direction": "credit", "amount_minor": 5_000},
        ],
    )
    assert txn["status"] == "posted"

    contra = await db.reverse_transaction(txn["id"], "test cleanup")
    original = await db.get_transaction(txn["id"])
    assert original is not None
    assert original["status"] == "reversed"
    assert contra["reverses_id"] == txn["id"]

    # A reversed transaction cannot be reversed again.
    with pytest.raises(ValueError, match="already reversed"):
        await db.reverse_transaction(txn["id"], "again")

    # The books still balance after the round-trip.
    tb = await db.trial_balance()
    assert tb["balanced"]


async def test_run_query_blocks_mutations():
    for sql in ("DELETE FROM transactions", "UPDATE accounts SET name='x'", "DROP TABLE accounts"):
        with pytest.raises(ValueError):
            await db.run_query(sql)


async def test_run_query_allows_select():
    rows = await db.run_query("SELECT COUNT(*) AS n FROM accounts")
    assert rows[0]["n"] == 10


async def test_run_query_allows_created_at_column():
    # Regression: a word-boundary blocklist must not reject `created_at`
    # just because it contains the substring "create".
    rows = await db.run_query("SELECT created_at FROM accounts LIMIT 1")
    assert "created_at" in rows[0]


async def test_reversal_is_contra_not_delete():
    # Posting then reversing must leave the original lines in place (contra),
    # and the touched accounts must net back to their pre-post balances.
    cash_before = (await db.get_balance("Cash"))["balance_minor"]
    rent_before = (await db.get_balance("Rent Expense"))["balance_minor"]

    txn = await db.post_transaction(
        "2026-06-03",
        "contra check",
        [
            {"account": "Rent Expense", "direction": "debit", "amount_minor": 7_000},
            {"account": "Cash", "direction": "credit", "amount_minor": 7_000},
        ],
    )
    await db.reverse_transaction(txn["id"], "undo")

    # Original lines still exist (not deleted).
    original = await db.get_transaction(txn["id"])
    assert original is not None and len(original["lines"]) == 2

    # Balances netted back to before the post.
    assert (await db.get_balance("Cash"))["balance_minor"] == cash_before
    assert (await db.get_balance("Rent Expense"))["balance_minor"] == rent_before


async def test_bool_amount_is_rejected():
    with pytest.raises(ValueError, match="positive integer"):
        await db.post_transaction(
            "2026-06-04",
            "bool amount",
            [
                {"account": "Cash", "direction": "debit", "amount_minor": True},
                {"account": "Sales Revenue", "direction": "credit", "amount_minor": True},
            ],
        )


async def test_transfer_to_same_account_is_rejected():
    with pytest.raises(ValueError, match="same account"):
        await db.transfer_funds("Cash", "Cash", 1_000, "2026-06-05")


async def test_profit_loss_values_for_january():
    pl = await db.profit_loss("2026-01-01", "2026-01-31")
    # Seeded January: one $4,000 sale, $1,800 rent expense, $3,000 payroll.
    assert pl["total_income_minor"] == 400_000
    assert pl["total_expenses_minor"] == 480_000
    assert pl["net_profit_minor"] == -80_000


async def test_balance_sheet_values_balance():
    bs = await db.balance_sheet()
    assert bs["total_assets_minor"] == bs["total_liabilities_minor"] + bs["total_equity_minor"]


async def test_as_of_balance_is_historical():
    # Balance as of a past date must not include later activity.
    early = await db.get_balance("Bank", as_of="2026-01-01")
    latest = await db.get_balance("Bank")
    assert early is not None and latest is not None
    # Jan 1 opening was a $50,000 owner investment into Bank.
    assert early["balance_minor"] == 5_000_000
    assert latest["balance_minor"] != early["balance_minor"]


async def test_duplicate_account_code_rejected():
    with pytest.raises(ValueError, match="already exists"):
        await db.create_account("1000", "Dup Cash", "asset")  # code 1000 already seeded
