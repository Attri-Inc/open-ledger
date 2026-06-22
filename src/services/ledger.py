"""Ledger use cases — posting, transfers, reversals, and transaction reads.

This is the single place the double-entry invariants are enforced, so REST and
MCP (and any future caller) cannot diverge in behaviour.
"""

from datetime import datetime

from src.domain.constants import DIRECTIONS
from src.domain.errors import ConflictError, NotFoundError, ValidationError
from src.infrastructure.database import Database
from src.infrastructure.identity import new_id, now_iso
from src.money import format_minor
from src.repositories.protocols import (
    AccountReader,
    AuditWriter,
    TransactionReader,
    TransactionWriter,
)


class LedgerService:
    def __init__(
        self,
        db: Database,
        accounts: AccountReader,
        transactions_read: TransactionReader,
        transactions_write: TransactionWriter,
        audit: AuditWriter,
    ):
        self._db = db
        self._accounts = accounts
        self._txn_read = transactions_read
        self._txn_write = transactions_write
        self._audit = audit

    # -- reads -----------------------------------------------------------------

    async def get_transaction(self, txn_id: str) -> dict | None:
        txn = await self._txn_read.get(txn_id)
        if not txn:
            return None
        lines = await self._txn_read.display_lines(txn_id)
        txn["lines"] = [{**line, "amount": format_minor(line["amount_minor"])} for line in lines]
        txn["total_minor"] = sum(
            line["amount_minor"] for line in lines if line["direction"] == "debit"
        )
        txn["total"] = format_minor(txn["total_minor"])
        return txn

    async def search(
        self,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        account: str | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict:
        account_id = None
        if account:
            resolved = await self._accounts.get(account)
            if not resolved:
                return {"items": [], "total": 0, "error": f"Account not found: {account}"}
            account_id = resolved["id"]
        rows, total = await self._txn_read.search(
            q, date_from, date_to, account_id, status, limit, offset
        )
        items = [{**r, "total": format_minor(r["total_minor"] or 0)} for r in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    # -- writes ----------------------------------------------------------------

    async def post(
        self,
        txn_date: str,
        description: str,
        lines: list[dict],
        reference: str | None = None,
        actor: str = "mcp",
        source: str = "mcp",
        audit_action: str = "post_transaction",
        audit_details: str | None = None,
    ) -> dict:
        if len(lines) < 2:
            raise ValidationError("A transaction needs at least 2 entry lines")
        try:
            datetime.strptime(txn_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValidationError(f"txn_date must be YYYY-MM-DD, got '{txn_date}'") from e

        resolved: list[tuple[dict, str, int, str | None]] = []
        debits = credits = 0
        for i, line in enumerate(lines, start=1):
            direction = line.get("direction")
            if direction not in DIRECTIONS:
                raise ValidationError(f"Line {i}: direction must be 'debit' or 'credit'")
            amount = line.get("amount_minor")
            # bool is a subclass of int — reject it so True can't post as 1 cent.
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                raise ValidationError(f"Line {i}: amount_minor must be a positive integer (cents)")
            account = await self._accounts.get(str(line.get("account", "")))
            if not account:
                raise NotFoundError(f"Line {i}: account not found: {line.get('account')}")
            if account["is_archived"]:
                raise ValidationError(
                    f"Line {i}: account {account['code']} · {account['name']} is archived"
                )
            debits += amount if direction == "debit" else 0
            credits += amount if direction == "credit" else 0
            resolved.append((account, direction, amount, line.get("memo")))

        if debits != credits:
            raise ValidationError(
                f"Unbalanced transaction: debits {format_minor(debits)} != "
                f"credits {format_minor(credits)}. Sum of debits must equal sum of credits."
            )

        txn_id = new_id("txn")
        now = now_iso()
        async with self._db.unit_of_work() as conn:
            await self._txn_write.insert(
                conn,
                {
                    "id": txn_id,
                    "txn_date": txn_date,
                    "description": description,
                    "reference": reference,
                    "source": source,
                    "created_at": now,
                    "created_by": actor,
                },
            )
            for line_no, (account, direction, amount, memo) in enumerate(resolved, start=1):
                await self._txn_write.insert_line(
                    conn,
                    {
                        "id": new_id("line"),
                        "transaction_id": txn_id,
                        "account_id": account["id"],
                        "line_no": line_no,
                        "direction": direction,
                        "amount_minor": amount,
                        "memo": memo,
                        "created_at": now,
                    },
                )
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": audit_action,
                    "object_type": "transaction",
                    "object_id": txn_id,
                    "details": audit_details
                    or f'Posted "{description}" · {format_minor(debits)} ({len(resolved)} lines)',
                    "created_at": now_iso(),
                },
            )
        return (await self.get_transaction(txn_id)) or {}

    async def transfer(
        self,
        from_account: str,
        to_account: str,
        amount_minor: int,
        txn_date: str,
        memo: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        src = await self._accounts.get(from_account)
        dst = await self._accounts.get(to_account)
        if not src:
            raise NotFoundError(f"Source account not found: {from_account}")
        if not dst:
            raise NotFoundError(f"Destination account not found: {to_account}")
        if src["id"] == dst["id"]:
            raise ValidationError("Cannot transfer to the same account")
        return await self.post(
            txn_date,
            f"Transfer: {src['name']} → {dst['name']}",
            [
                {
                    "account": src["id"],
                    "direction": "credit",
                    "amount_minor": amount_minor,
                    "memo": memo,
                },
                {
                    "account": dst["id"],
                    "direction": "debit",
                    "amount_minor": amount_minor,
                    "memo": memo,
                },
            ],
            reference="TRF",
            actor=actor,
            audit_action="transfer_funds",
            audit_details=f"Transferred {format_minor(amount_minor)}: {src['name']} → {dst['name']}",
        )

    async def reverse(self, txn_id: str, reason: str, actor: str = "mcp") -> dict:
        original = await self.get_transaction(txn_id)
        if not original:
            raise NotFoundError(f"Transaction not found: {txn_id}")
        if original["status"] == "reversed":
            raise ConflictError(
                f"Transaction {txn_id} is already reversed (by {original['reversed_by_id']})"
            )
        if original["reverses_id"]:
            raise ConflictError(f"Transaction {txn_id} is itself a reversal and cannot be reversed")

        contra_id = new_id("txn")
        now = now_iso()
        raw_lines = await self._txn_read.raw_lines(txn_id)
        async with self._db.unit_of_work() as conn:
            # Date the contra at the ORIGINAL date so historical (as_of) reports stay consistent.
            await self._txn_write.insert(
                conn,
                {
                    "id": contra_id,
                    "txn_date": original["txn_date"],
                    "description": f"Reversal of: {original['description']} — {reason}",
                    "reference": original.get("reference"),
                    "reverses_id": txn_id,
                    "source": "mcp",
                    "created_at": now,
                    "created_by": actor,
                },
            )
            for line in raw_lines:
                await self._txn_write.insert_line(
                    conn,
                    {
                        "id": new_id("line"),
                        "transaction_id": contra_id,
                        "account_id": line["account_id"],
                        "line_no": line["line_no"],
                        "direction": "credit" if line["direction"] == "debit" else "debit",
                        "amount_minor": line["amount_minor"],
                        "memo": line["memo"],
                        "created_at": now,
                    },
                )
            await self._txn_write.mark_reversed(conn, txn_id, contra_id)
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "reverse_transaction",
                    "object_type": "transaction",
                    "object_id": contra_id,
                    "details": f'Reversed "{original["description"]}" ({txn_id}): {reason}',
                    "created_at": now_iso(),
                },
            )
        return (await self.get_transaction(contra_id)) or {}
