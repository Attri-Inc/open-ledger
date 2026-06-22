"""Composition root — the only place concrete implementations are chosen and wired.

Everything else depends on protocols. To swap SQLite for Postgres, you implement
the repository protocols and change this file; no service or tool changes.
"""

from src.config import DB_PATH
from src.infrastructure.database import Database
from src.repositories.sqlite import (
    SqliteAccountRepository,
    SqliteAuditRepository,
    SqliteQueryRepository,
    SqliteTransactionRepository,
)
from src.services.accounts import AccountService
from src.services.audit import AuditService
from src.services.ledger import LedgerService
from src.services.query import QueryService
from src.services.reports import ReportService


class Container:
    def __init__(self, db_path: str = DB_PATH):
        self.database = Database(db_path)

        accounts_repo = SqliteAccountRepository(self.database)
        transactions_repo = SqliteTransactionRepository(self.database)
        audit_repo = SqliteAuditRepository(self.database)
        query_repo = SqliteQueryRepository(self.database)

        self.accounts = AccountService(self.database, accounts_repo, accounts_repo, audit_repo)
        self.ledger = LedgerService(
            self.database, accounts_repo, transactions_repo, transactions_repo, audit_repo
        )
        self.reports = ReportService(accounts_repo)
        self.audit = AuditService(audit_repo)
        self.queries = QueryService(query_repo)

    async def close(self) -> None:
        await self.database.close()


# Process-wide singleton used by the MCP server.
container = Container()
