"""SQLite implementations of the repository protocols.

These are the only classes that know SQL exists. Reads use the engine-enforced
read-only connection; writes run on the connection passed from a Unit of Work.
"""

from typing import Any

import aiosqlite

from src.domain.errors import ConflictError
from src.infrastructure.database import Database, fetch_all


class SqliteAccountRepository:
    def __init__(self, db: Database):
        self._db = db

    async def get(self, identifier: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT * FROM accounts WHERE id = ? OR code = ? OR name = ? COLLATE NOCASE "
            "ORDER BY (id = ?) DESC, (code = ?) DESC LIMIT 1",
            (identifier, identifier, identifier, identifier, identifier),
        )
        return dict(rows[0]) if rows else None

    async def get_by_id(self, account_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(conn, "SELECT * FROM accounts WHERE id = ?", [account_id])
        return dict(rows[0]) if rows else None

    async def list_rows(
        self, account_type: str | None, include_archived: bool, q: str | None
    ) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if account_type:
            conditions.append("type = ?")
            params.append(account_type)
        if not include_archived:
            conditions.append("is_archived = 0")
        if q:
            conditions.append("(name LIKE ? OR code LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        rows = await fetch_all(
            conn, f"SELECT * FROM accounts WHERE {' AND '.join(conditions)} ORDER BY code", params
        )
        return [dict(r) for r in rows]

    async def net_debit(self, account_id: str, as_of: str | None) -> int:
        conn = await self._db.connection()
        date_clause = "AND t.txn_date <= ?" if as_of else ""
        params = [account_id] + ([as_of] if as_of else [])
        rows = await fetch_all(
            conn,
            f"""
            SELECT COALESCE(SUM(CASE WHEN l.direction = 'debit' THEN l.amount_minor
                                     ELSE -l.amount_minor END), 0) AS net_debit
            FROM entry_lines l
            JOIN transactions t ON l.transaction_id = t.id
            WHERE l.account_id = ? {date_clause}
            """,
            params,
        )
        return int(dict(rows[0])["net_debit"])

    async def ledger_rows(self, account_id: str, date_to: str | None) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["l.account_id = ?"], [account_id]
        if date_to:
            conditions.append("t.txn_date <= ?")
            params.append(date_to)
        rows = await fetch_all(
            conn,
            f"""
            SELECT t.txn_date, t.description, t.reference, t.status, t.id AS transaction_id,
                   l.direction, l.amount_minor, l.memo
            FROM entry_lines l
            JOIN transactions t ON l.transaction_id = t.id
            WHERE {" AND ".join(conditions)}
            ORDER BY t.txn_date, t.created_at, l.line_no
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def type_totals(
        self, account_type: str, date_from: str | None, date_to: str | None
    ) -> list[dict]:
        conn = await self._db.connection()
        conditions, params = ["a.type = ?", "a.is_archived = 0"], [account_type]
        if date_from:
            conditions.append("t.txn_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("t.txn_date <= ?")
            params.append(date_to)
        rows = await fetch_all(
            conn,
            f"""
            SELECT a.code, a.name, a.normal_side,
                   COALESCE(SUM(CASE WHEN l.direction = 'debit' THEN l.amount_minor
                                     ELSE -l.amount_minor END), 0) AS net_debit
            FROM accounts a
            JOIN entry_lines l ON l.account_id = a.id
            JOIN transactions t ON l.transaction_id = t.id
            WHERE {" AND ".join(conditions)}
            GROUP BY a.id ORDER BY a.code
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def trial_balance_rows(self, as_of: str | None) -> list[dict]:
        conn = await self._db.connection()
        date_clause = "WHERE t.txn_date <= ?" if as_of else ""
        params = [as_of] if as_of else []
        rows = await fetch_all(
            conn,
            f"""
            SELECT a.id, a.code, a.name, a.type, a.normal_side,
                   COALESCE(SUM(CASE WHEN le.direction = 'debit' THEN le.amount_minor ELSE 0 END), 0) AS debits,
                   COALESCE(SUM(CASE WHEN le.direction = 'credit' THEN le.amount_minor ELSE 0 END), 0) AS credits
            FROM accounts a
            LEFT JOIN (
                SELECT l.account_id, l.direction, l.amount_minor
                FROM entry_lines l JOIN transactions t ON l.transaction_id = t.id
                {date_clause}
            ) le ON le.account_id = a.id
            WHERE a.is_archived = 0
            GROUP BY a.id ORDER BY a.code
            """,
            params,
        )
        return [dict(r) for r in rows]

    async def insert(self, conn: Any, account: dict) -> None:
        try:
            await conn.execute(
                "INSERT INTO accounts (id, code, name, type, normal_side, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    account["id"],
                    account["code"],
                    account["name"],
                    account["type"],
                    account["normal_side"],
                    account.get("description"),
                    account["created_at"],
                    account["updated_at"],
                ),
            )
        except aiosqlite.IntegrityError as e:
            raise ConflictError(f"Account code or name already exists: {e}") from e


class SqliteTransactionRepository:
    def __init__(self, db: Database):
        self._db = db

    async def get(self, txn_id: str) -> dict | None:
        conn = await self._db.connection()
        rows = await fetch_all(conn, "SELECT * FROM transactions WHERE id = ?", [txn_id])
        return dict(rows[0]) if rows else None

    async def display_lines(self, txn_id: str) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            """
            SELECT l.line_no, l.direction, l.amount_minor, l.memo,
                   a.code AS account_code, a.name AS account_name
            FROM entry_lines l JOIN accounts a ON l.account_id = a.id
            WHERE l.transaction_id = ? ORDER BY l.line_no
            """,
            [txn_id],
        )
        return [dict(r) for r in rows]

    async def raw_lines(self, txn_id: str) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(
            conn,
            "SELECT account_id, line_no, direction, amount_minor, memo "
            "FROM entry_lines WHERE transaction_id = ? ORDER BY line_no",
            [txn_id],
        )
        return [dict(r) for r in rows]

    async def search(
        self,
        q: str | None,
        date_from: str | None,
        date_to: str | None,
        account_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if q:
            conditions.append("(t.description LIKE ? OR t.reference LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if date_from:
            conditions.append("t.txn_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("t.txn_date <= ?")
            params.append(date_to)
        if status:
            conditions.append("t.status = ?")
            params.append(status)
        if account_id:
            conditions.append(
                "t.id IN (SELECT transaction_id FROM entry_lines WHERE account_id = ?)"
            )
            params.append(account_id)
        where = " AND ".join(conditions)

        count_rows = await fetch_all(
            conn, f"SELECT COUNT(*) AS cnt FROM transactions t WHERE {where}", params
        )
        total = int(dict(count_rows[0])["cnt"])

        rows = await fetch_all(
            conn,
            f"""
            SELECT t.id, t.txn_date, t.description, t.reference, t.status,
                   t.reverses_id, t.reversed_by_id, t.source, t.created_by,
                   (SELECT SUM(amount_minor) FROM entry_lines WHERE transaction_id = t.id AND direction = 'debit') AS total_minor,
                   (SELECT COUNT(*) FROM entry_lines WHERE transaction_id = t.id) AS line_count
            FROM transactions t
            WHERE {where}
            ORDER BY t.txn_date DESC, t.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        )
        return [dict(r) for r in rows], total

    async def insert(self, conn: Any, txn: dict) -> None:
        await conn.execute(
            "INSERT INTO transactions (id, txn_date, description, reference, reverses_id, source, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                txn["id"],
                txn["txn_date"],
                txn["description"],
                txn.get("reference"),
                txn.get("reverses_id"),
                txn["source"],
                txn["created_at"],
                txn["created_by"],
            ),
        )

    async def insert_line(self, conn: Any, line: dict) -> None:
        await conn.execute(
            "INSERT INTO entry_lines (id, transaction_id, account_id, line_no, direction, amount_minor, memo, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                line["id"],
                line["transaction_id"],
                line["account_id"],
                line["line_no"],
                line["direction"],
                line["amount_minor"],
                line.get("memo"),
                line["created_at"],
            ),
        )

    async def mark_reversed(self, conn: Any, original_id: str, contra_id: str) -> None:
        await conn.execute(
            "UPDATE transactions SET status = 'reversed', reversed_by_id = ? WHERE id = ?",
            (contra_id, original_id),
        )


class SqliteAuditRepository:
    def __init__(self, db: Database):
        self._db = db

    async def list(
        self, action: str | None, actor: str | None, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        conn = await self._db.connection()
        conditions, params = ["1=1"], []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        where = " AND ".join(conditions)
        count_rows = await fetch_all(
            conn, f"SELECT COUNT(*) AS cnt FROM audit_log WHERE {where}", params
        )
        rows = await fetch_all(
            conn,
            f"SELECT * FROM audit_log WHERE {where} ORDER BY seq DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        return [dict(r) for r in rows], int(dict(count_rows[0])["cnt"])

    async def append(self, conn: Any, entry: dict) -> None:
        await conn.execute(
            "INSERT INTO audit_log (id, actor, action, object_type, object_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry["id"],
                entry["actor"],
                entry["action"],
                entry["object_type"],
                entry.get("object_id"),
                entry["details"],
                entry["created_at"],
            ),
        )


class SqliteQueryRepository:
    def __init__(self, db: Database):
        self._db = db

    async def select(self, sql: str) -> list[dict]:
        conn = await self._db.connection()
        rows = await fetch_all(conn, sql)
        return [dict(r) for r in rows[:500]]
