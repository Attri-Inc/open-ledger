"""Repository contracts (Protocols).

Services depend on these, never on the concrete SQLite classes (Dependency
Inversion). They are split into narrow Reader/Writer roles (Interface
Segregation): a report service receives only a reader and *cannot* mutate.

Write methods take an opaque `conn` (the connection yielded by a Unit of Work),
so the same transaction spans every write in a use case. The connection type is
intentionally `Any` to keep the contract backend-agnostic.
"""

from typing import Any, Protocol


class AccountReader(Protocol):
    async def get(self, identifier: str) -> dict | None: ...
    async def get_by_id(self, account_id: str) -> dict | None: ...
    async def list_rows(
        self, account_type: str | None, include_archived: bool, q: str | None
    ) -> list[dict]: ...
    async def net_debit(self, account_id: str, as_of: str | None) -> int: ...
    async def ledger_rows(self, account_id: str, date_to: str | None) -> list[dict]: ...
    async def type_totals(
        self, account_type: str, date_from: str | None, date_to: str | None
    ) -> list[dict]: ...
    async def trial_balance_rows(self, as_of: str | None) -> list[dict]: ...


class AccountWriter(Protocol):
    async def insert(self, conn: Any, account: dict) -> None: ...


class TransactionReader(Protocol):
    async def get(self, txn_id: str) -> dict | None: ...
    async def display_lines(self, txn_id: str) -> list[dict]: ...
    async def raw_lines(self, txn_id: str) -> list[dict]: ...
    async def search(
        self,
        q: str | None,
        date_from: str | None,
        date_to: str | None,
        account_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]: ...


class TransactionWriter(Protocol):
    async def insert(self, conn: Any, txn: dict) -> None: ...
    async def insert_line(self, conn: Any, line: dict) -> None: ...
    async def mark_reversed(self, conn: Any, original_id: str, contra_id: str) -> None: ...


class AuditReader(Protocol):
    async def list(
        self, action: str | None, actor: str | None, limit: int, offset: int
    ) -> tuple[list[dict], int]: ...


class AuditWriter(Protocol):
    async def append(self, conn: Any, entry: dict) -> None: ...


class QueryRunner(Protocol):
    async def select(self, sql: str) -> list[dict]: ...
