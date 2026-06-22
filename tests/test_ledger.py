"""Tests for the core double-entry invariants, run through the service layer."""

import pytest

from src.container import container
from src.domain.errors import ConflictError, ValidationError

accounts = container.accounts
ledger = container.ledger
reports = container.reports
queries = container.queries


async def test_chart_of_accounts_seeded():
    rows = await accounts.list_accounts()
    assert len(rows) == 10
    codes = {a["code"] for a in rows}
    assert {"1000", "1010", "3000", "4000", "5100"} <= codes


async def test_seeded_books_balance():
    tb = await reports.trial_balance()
    assert tb["balanced"]
    assert tb["total_debit_minor"] == tb["total_credit_minor"]


async def test_balance_sheet_equation_holds():
    bs = await reports.balance_sheet()
    assert bs["equation_holds"]


async def test_balance_positive_on_normal_side():
    bank = await accounts.balance("Bank")
    assert bank is not None
    assert bank["balance_minor"] > 0


async def test_post_unbalanced_is_rejected():
    with pytest.raises(ValidationError, match="[Uu]nbalanced"):
        await ledger.post(
            "2026-06-01",
            "bad entry",
            [
                {"account": "Cash", "direction": "debit", "amount_minor": 100},
                {"account": "Sales Revenue", "direction": "credit", "amount_minor": 200},
            ],
        )


async def test_post_requires_two_lines():
    with pytest.raises(ValidationError, match="at least 2"):
        await ledger.post(
            "2026-06-01",
            "single line",
            [{"account": "Cash", "direction": "debit", "amount_minor": 100}],
        )


async def test_post_then_reverse_restores_balance_and_is_immutable():
    txn = await ledger.post(
        "2026-06-02",
        "office supplies (test)",
        [
            {"account": "Rent Expense", "direction": "debit", "amount_minor": 5_000},
            {"account": "Cash", "direction": "credit", "amount_minor": 5_000},
        ],
    )
    assert txn["status"] == "posted"

    contra = await ledger.reverse(txn["id"], "test cleanup")
    original = await ledger.get_transaction(txn["id"])
    assert original is not None
    assert original["status"] == "reversed"
    assert contra["reverses_id"] == txn["id"]

    with pytest.raises(ConflictError, match="already reversed"):
        await ledger.reverse(txn["id"], "again")

    tb = await reports.trial_balance()
    assert tb["balanced"]


async def test_run_query_blocks_mutations():
    for sql in ("DELETE FROM transactions", "UPDATE accounts SET name='x'", "DROP TABLE accounts"):
        with pytest.raises(ValidationError):
            await queries.run(sql)


async def test_run_query_allows_select():
    rows = await queries.run("SELECT COUNT(*) AS n FROM accounts")
    assert rows[0]["n"] == 10


async def test_run_query_allows_created_at_column():
    # Regression: a word-boundary blocklist must not reject `created_at`
    # just because it contains the substring "create".
    rows = await queries.run("SELECT created_at FROM accounts LIMIT 1")
    assert "created_at" in rows[0]


async def test_reversal_is_contra_not_delete():
    cash_before = (await accounts.balance("Cash"))["balance_minor"]
    rent_before = (await accounts.balance("Rent Expense"))["balance_minor"]

    txn = await ledger.post(
        "2026-06-03",
        "contra check",
        [
            {"account": "Rent Expense", "direction": "debit", "amount_minor": 7_000},
            {"account": "Cash", "direction": "credit", "amount_minor": 7_000},
        ],
    )
    await ledger.reverse(txn["id"], "undo")

    original = await ledger.get_transaction(txn["id"])
    assert original is not None and len(original["lines"]) == 2

    assert (await accounts.balance("Cash"))["balance_minor"] == cash_before
    assert (await accounts.balance("Rent Expense"))["balance_minor"] == rent_before


async def test_bool_amount_is_rejected():
    with pytest.raises(ValidationError, match="positive integer"):
        await ledger.post(
            "2026-06-04",
            "bool amount",
            [
                {"account": "Cash", "direction": "debit", "amount_minor": True},
                {"account": "Sales Revenue", "direction": "credit", "amount_minor": True},
            ],
        )


async def test_transfer_to_same_account_is_rejected():
    with pytest.raises(ValidationError, match="same account"):
        await ledger.transfer("Cash", "Cash", 1_000, "2026-06-05")


async def test_profit_loss_values_for_january():
    pl = await reports.profit_loss("2026-01-01", "2026-01-31")
    assert pl["total_income_minor"] == 400_000
    assert pl["total_expenses_minor"] == 480_000
    assert pl["net_profit_minor"] == -80_000


async def test_balance_sheet_values_balance():
    bs = await reports.balance_sheet()
    assert bs["total_assets_minor"] == bs["total_liabilities_minor"] + bs["total_equity_minor"]


async def test_as_of_balance_is_historical():
    early = await accounts.balance("Bank", as_of="2026-01-01")
    latest = await accounts.balance("Bank")
    assert early is not None and latest is not None
    assert early["balance_minor"] == 5_000_000
    assert latest["balance_minor"] != early["balance_minor"]


async def test_duplicate_account_code_rejected():
    with pytest.raises(ConflictError, match="already exists"):
        await accounts.create("1000", "Dup Cash", "asset")


async def test_resolve_account_priority_is_deterministic():
    # "1000" is account Cash's code; resolution must return the code match.
    resolved = await accounts.resolve("1000")
    assert resolved is not None and resolved["name"] == "Cash"
