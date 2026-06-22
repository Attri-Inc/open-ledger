"""Financial reports as interchangeable strategies.

Each report is a ReportStrategy. Adding one (e.g. Cash Flow) means adding a class
and a ReportService method — nothing existing changes (Open/Closed). Reports get
only an AccountReader, so they *cannot* mutate the ledger (Interface Segregation).
"""

from typing import Protocol

from src.money import format_minor
from src.repositories.protocols import AccountReader


async def _type_total(
    accounts: AccountReader, account_type: str, date_from: str | None, date_to: str | None
) -> tuple[int, list[dict]]:
    """Total for an account type on its normal side, plus per-account rows."""
    rows = await accounts.type_totals(account_type, date_from, date_to)
    items, total = [], 0
    for row in rows:
        bal = row["net_debit"] if row["normal_side"] == "debit" else -row["net_debit"]
        total += bal
        items.append(
            {
                "code": row["code"],
                "name": row["name"],
                "balance_minor": bal,
                "balance": format_minor(bal),
            }
        )
    return total, items


class ReportStrategy(Protocol):
    async def generate(self) -> dict: ...


class TrialBalanceReport:
    def __init__(self, accounts: AccountReader, as_of: str | None = None):
        self._accounts = accounts
        self._as_of = as_of

    async def generate(self) -> dict:
        rows = await self._accounts.trial_balance_rows(self._as_of)
        accounts, total_debit, total_credit = [], 0, 0
        for row in rows:
            net = row["debits"] - row["credits"]
            debit_bal = net if net > 0 else 0
            credit_bal = -net if net < 0 else 0
            total_debit += debit_bal
            total_credit += credit_bal
            accounts.append(
                {
                    "code": row["code"],
                    "name": row["name"],
                    "type": row["type"],
                    "debit_minor": debit_bal,
                    "debit": format_minor(debit_bal),
                    "credit_minor": credit_bal,
                    "credit": format_minor(credit_bal),
                }
            )
        return {
            "as_of": self._as_of or "latest",
            "accounts": accounts,
            "total_debit_minor": total_debit,
            "total_debit": format_minor(total_debit),
            "total_credit_minor": total_credit,
            "total_credit": format_minor(total_credit),
            "balanced": total_debit == total_credit,
        }


class ProfitLossReport:
    def __init__(
        self, accounts: AccountReader, date_from: str | None = None, date_to: str | None = None
    ):
        self._accounts = accounts
        self._from = date_from
        self._to = date_to

    async def generate(self) -> dict:
        income_total, income = await _type_total(self._accounts, "income", self._from, self._to)
        expense_total, expenses = await _type_total(self._accounts, "expense", self._from, self._to)
        net = income_total - expense_total
        return {
            "period": {"from": self._from or "beginning", "to": self._to or "latest"},
            "income": income,
            "total_income_minor": income_total,
            "total_income": format_minor(income_total),
            "expenses": expenses,
            "total_expenses_minor": expense_total,
            "total_expenses": format_minor(expense_total),
            "net_profit_minor": net,
            "net_profit": format_minor(net),
        }


class BalanceSheetReport:
    def __init__(self, accounts: AccountReader, as_of: str | None = None):
        self._accounts = accounts
        self._as_of = as_of

    async def generate(self) -> dict:
        assets_total, assets = await _type_total(self._accounts, "asset", None, self._as_of)
        liab_total, liabilities = await _type_total(self._accounts, "liability", None, self._as_of)
        equity_total, equity = await _type_total(self._accounts, "equity", None, self._as_of)
        income_total, _ = await _type_total(self._accounts, "income", None, self._as_of)
        expense_total, _ = await _type_total(self._accounts, "expense", None, self._as_of)
        earnings = income_total - expense_total
        equity_with_earnings = equity_total + earnings
        return {
            "as_of": self._as_of or "latest",
            "assets": assets,
            "total_assets_minor": assets_total,
            "total_assets": format_minor(assets_total),
            "liabilities": liabilities,
            "total_liabilities_minor": liab_total,
            "total_liabilities": format_minor(liab_total),
            "equity": equity
            + [
                {
                    "code": "—",
                    "name": "Current Earnings",
                    "balance_minor": earnings,
                    "balance": format_minor(earnings),
                }
            ],
            "total_equity_minor": equity_with_earnings,
            "total_equity": format_minor(equity_with_earnings),
            "equation_holds": assets_total == liab_total + equity_with_earnings,
        }


class ReportService:
    def __init__(self, accounts: AccountReader):
        self._accounts = accounts

    async def trial_balance(self, as_of: str | None = None) -> dict:
        return await TrialBalanceReport(self._accounts, as_of).generate()

    async def profit_loss(self, date_from: str | None = None, date_to: str | None = None) -> dict:
        return await ProfitLossReport(self._accounts, date_from, date_to).generate()

    async def balance_sheet(self, as_of: str | None = None) -> dict:
        return await BalanceSheetReport(self._accounts, as_of).generate()
