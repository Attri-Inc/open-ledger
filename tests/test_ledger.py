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
