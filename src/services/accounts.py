"""Account use cases. Depends only on repository protocols (Dependency Inversion)."""

from src.domain.constants import NORMAL_SIDE
from src.domain.errors import ValidationError
from src.infrastructure.database import Database
from src.infrastructure.identity import new_id, now_iso
from src.money import format_minor
from src.repositories.protocols import AccountReader, AccountWriter, AuditWriter


class AccountService:
    def __init__(
        self,
        db: Database,
        reader: AccountReader,
        writer: AccountWriter,
        audit: AuditWriter,
    ):
        self._db = db
        self._reader = reader
        self._writer = writer
        self._audit = audit

    async def resolve(self, identifier: str) -> dict | None:
        return await self._reader.get(identifier)

    async def _signed_balance(self, account: dict, as_of: str | None = None) -> int:
        net = await self._reader.net_debit(account["id"], as_of)
        return net if account["normal_side"] == "debit" else -net

    async def list_accounts(
        self, account_type: str | None = None, include_archived: bool = False, q: str | None = None
    ) -> list[dict]:
        rows = await self._reader.list_rows(account_type, include_archived, q)
        result = []
        for account in rows:
            bal = await self._signed_balance(account)
            result.append({**account, "balance_minor": bal, "balance": format_minor(bal)})
        return result

    async def balance(self, identifier: str, as_of: str | None = None) -> dict | None:
        account = await self.resolve(identifier)
        if not account:
            return None
        bal = await self._signed_balance(account, as_of)
        return {
            "account_id": account["id"],
            "code": account["code"],
            "name": account["name"],
            "type": account["type"],
            "normal_side": account["normal_side"],
            "as_of": as_of or "latest",
            "balance_minor": bal,
            "balance": format_minor(bal),
        }

    async def with_balance(self, identifier: str) -> dict | None:
        account = await self.resolve(identifier)
        if not account:
            return None
        bal = await self._signed_balance(account)
        return {**account, "balance_minor": bal, "balance": format_minor(bal)}

    async def ledger(
        self,
        identifier: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> dict | None:
        account = await self.resolve(identifier)
        if not account:
            return None
        # Full history up to date_to so the running balance carries the opening
        # balance forward; date_from only filters which rows are displayed.
        rows = await self._reader.ledger_rows(account["id"], date_to)
        sign = 1 if account["normal_side"] == "debit" else -1
        running = 0
        entries = []
        for entry in rows:
            running += sign * (
                entry["amount_minor"] if entry["direction"] == "debit" else -entry["amount_minor"]
            )
            entry["amount"] = format_minor(entry["amount_minor"])
            entry["running_balance_minor"] = running
            entry["running_balance"] = format_minor(running)
            if date_from is None or entry["txn_date"] >= date_from:
                entries.append(entry)
        return {
            "account": {
                "id": account["id"],
                "code": account["code"],
                "name": account["name"],
                "type": account["type"],
            },
            "entries": entries[-limit:],
            "ending_balance_minor": running,
            "ending_balance": format_minor(running),
        }

    async def create(
        self,
        code: str,
        name: str,
        account_type: str,
        description: str | None = None,
        actor: str = "mcp",
    ) -> dict:
        if account_type not in NORMAL_SIDE:
            raise ValidationError(
                f"Invalid account type '{account_type}'. Must be one of: {', '.join(NORMAL_SIDE)}"
            )
        acct_id = new_id("acc")
        now = now_iso()
        account = {
            "id": acct_id,
            "code": code,
            "name": name,
            "type": account_type,
            "normal_side": NORMAL_SIDE[account_type],
            "description": description,
            "created_at": now,
            "updated_at": now,
        }
        async with self._db.unit_of_work() as conn:
            await self._writer.insert(conn, account)  # raises ConflictError on duplicate
            await self._audit.append(
                conn,
                {
                    "id": new_id("aud"),
                    "actor": actor,
                    "action": "create_account",
                    "object_type": "account",
                    "object_id": acct_id,
                    "details": f"Created account {code} · {name} ({account_type})",
                    "created_at": now_iso(),
                },
            )
        return (await self.with_balance(acct_id)) or {}
