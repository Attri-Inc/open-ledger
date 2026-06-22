"""OpenLedger database layer — all query and posting functions.

Shared by the MCP server. SQLite double-entry ledger:
- All amounts are integer minor units (cents).
- Transactions are immutable; corrections via reverse_transaction (contra posting).
- Every mutation writes an audit_log row in the same DB transaction.
"""

import asyncio
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import aiosqlite

from src.config import DB_PATH
from src.money import format_minor as _fmt

NORMAL_SIDE = {
    "asset": "debit",
    "expense": "debit",
    "liability": "credit",
    "equity": "credit",
    "income": "credit",
}

_db: aiosqlite.Connection | None = None
_ro_db: aiosqlite.Connection | None = None
# Serializes write operations so a mutation and its audit row commit together,
# even if MCP requests interleave on the single shared connection.
_write_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def get_ro_db() -> aiosqlite.Connection:
    """A separate connection enforced read-only at the engine level (query_only)."""
    global _ro_db
    if _ro_db is None:
        _ro_db = await aiosqlite.connect(DB_PATH)
        _ro_db.row_factory = aiosqlite.Row
        await _ro_db.execute("PRAGMA foreign_keys=ON")
        await _ro_db.execute("PRAGMA query_only=ON")
    return _ro_db


async def close_db():
    global _db, _ro_db
    if _db:
        await _db.close()
        _db = None
    if _ro_db:
        await _ro_db.close()
        _ro_db = None


async def _rows(
    db: aiosqlite.Connection, sql: str, params: Sequence[object] = ()
) -> list[aiosqlite.Row]:
    """Run a query and return rows as a real list (aiosqlite types fetchall as a
    non-indexable Iterable; materializing it keeps both runtime and mypy happy)."""
    return list(await db.execute_fetchall(sql, params))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def _audit(
    db: aiosqlite.Connection,
    actor: str,
    action: str,
    object_type: str,
    object_id: str | None,
    details: str,
):
    """Append an audit row. Caller commits — same transaction as the mutation."""
    await db.execute(
        "INSERT INTO audit_log (id, actor, action, object_type, object_id, details, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_new_id("aud"), actor, action, object_type, object_id, details, _now()),
    )


async def resolve_account(identifier: str) -> dict | None:
    """Find an account by id, code, or name (case-insensitive).

    Resolution is deterministic with priority id > code > name, so an
    identifier that happens to match one account's code and another's name
    always resolves to the code match, never to whichever row SQLite returns first.
    """
    db = await get_db()
    rows = await _rows(
        db,
        "SELECT * FROM accounts WHERE id = ? OR code = ? OR name = ? COLLATE NOCASE "
        "ORDER BY (id = ?) DESC, (code = ?) DESC LIMIT 1",
        (identifier, identifier, identifier, identifier, identifier),
    )
    return dict(rows[0]) if rows else None


# ---------------------------------------------------------------------------
# Accounts (read)
# ---------------------------------------------------------------------------


async def list_accounts(
    account_type: str | None = None, include_archived: bool = False, q: str | None = None
) -> list[dict]:
    db = await get_db()
    conditions, params = ["1=1"], []
    if account_type:
        conditions.append("type = ?")
        params.append(account_type)
    if not include_archived:
        conditions.append("is_archived = 0")
    if q:
        conditions.append("(name LIKE ? OR code LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    rows = await _rows(
        db, f"SELECT * FROM accounts WHERE {' AND '.join(conditions)} ORDER BY code", params
    )
    result = []
    for r in rows:
        acct = dict(r)
        acct["balance_minor"] = await _account_balance(acct["id"])
        acct["balance"] = _fmt(acct["balance_minor"])
        result.append(acct)
    return result


async def _account_balance(account_id: str, as_of: str | None = None) -> int:
    """Signed balance in minor units, positive on the account's normal side."""
    db = await get_db()
    date_clause = "AND t.txn_date <= ?" if as_of else ""
    params = [account_id] + ([as_of] if as_of else [])
    rows = await _rows(
        db,
        f"""
        SELECT COALESCE(SUM(CASE WHEN l.direction = 'debit' THEN l.amount_minor ELSE -l.amount_minor END), 0) AS net_debit
        FROM entry_lines l
        JOIN transactions t ON l.transaction_id = t.id
        WHERE l.account_id = ? {date_clause}
    """,
        params,
    )
    net_debit = dict(rows[0])["net_debit"]
    acct = await _rows(db, "SELECT normal_side FROM accounts WHERE id = ?", [account_id])
    if not acct:
        return 0
    side = dict(acct[0])["normal_side"]
    return net_debit if side == "debit" else -net_debit


async def get_balance(identifier: str, as_of: str | None = None) -> dict | None:
    acct = await resolve_account(identifier)
    if not acct:
        return None
    bal = await _account_balance(acct["id"], as_of)
    return {
        "account_id": acct["id"],
        "code": acct["code"],
        "name": acct["name"],
        "type": acct["type"],
        "normal_side": acct["normal_side"],
        "as_of": as_of or "latest",
        "balance_minor": bal,
        "balance": _fmt(bal),
    }


async def get_account_ledger(
    identifier: str, date_from: str | None = None, date_to: str | None = None, limit: int = 100
) -> dict | None:
    """Entry lines for one account with a running balance."""
    acct = await resolve_account(identifier)
    if not acct:
        return None
    db = await get_db()
    # Fetch the full history up to date_to so the running balance carries the
    # opening balance forward; date_from only filters which rows are *displayed*.
    conditions, params = ["l.account_id = ?"], [acct["id"]]
    if date_to:
        conditions.append("t.txn_date <= ?")
        params.append(date_to)
    rows = await _rows(
        db,
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

    sign = 1 if acct["normal_side"] == "debit" else -1
    running = 0
    entries = []
    for r in rows:
        e = dict(r)
        running += sign * (e["amount_minor"] if e["direction"] == "debit" else -e["amount_minor"])
        e["amount"] = _fmt(e["amount_minor"])
        e["running_balance_minor"] = running
        e["running_balance"] = _fmt(running)
        if date_from is None or e["txn_date"] >= date_from:
            entries.append(e)
    return {
        "account": {
            "id": acct["id"],
            "code": acct["code"],
            "name": acct["name"],
            "type": acct["type"],
        },
        "entries": entries[-limit:],
        "ending_balance_minor": running,
        "ending_balance": _fmt(running),
    }


# ---------------------------------------------------------------------------
# Transactions (read)
# ---------------------------------------------------------------------------


async def get_transaction(txn_id: str) -> dict | None:
    db = await get_db()
    rows = await _rows(db, "SELECT * FROM transactions WHERE id = ?", [txn_id])
    if not rows:
        return None
    txn = dict(rows[0])
    lines = await _rows(
        db,
        """
        SELECT l.line_no, l.direction, l.amount_minor, l.memo,
               a.code AS account_code, a.name AS account_name
        FROM entry_lines l JOIN accounts a ON l.account_id = a.id
        WHERE l.transaction_id = ? ORDER BY l.line_no
    """,
        [txn_id],
    )
    txn["lines"] = [{**dict(line), "amount": _fmt(dict(line)["amount_minor"])} for line in lines]
    txn["total_minor"] = sum(
        line["amount_minor"] for line in txn["lines"] if line["direction"] == "debit"
    )
    txn["total"] = _fmt(txn["total_minor"])
    return txn


async def search_transactions(
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    db = await get_db()
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
    if account:
        acct = await resolve_account(account)
        if not acct:
            return {"items": [], "total": 0, "error": f"Account not found: {account}"}
        conditions.append("t.id IN (SELECT transaction_id FROM entry_lines WHERE account_id = ?)")
        params.append(acct["id"])
    where = " AND ".join(conditions)

    count = await _rows(db, f"SELECT COUNT(*) AS cnt FROM transactions t WHERE {where}", params)
    total = dict(count[0])["cnt"]

    rows = await _rows(
        db,
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
    items = []
    for r in rows:
        item = dict(r)
        item["total"] = _fmt(item["total_minor"] or 0)
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


async def trial_balance(as_of: str | None = None) -> dict:
    db = await get_db()
    date_clause = "WHERE t.txn_date <= ?" if as_of else ""
    params = [as_of] if as_of else []
    rows = await _rows(
        db,
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

    accounts, total_debit, total_credit = [], 0, 0
    for r in rows:
        a = dict(r)
        net = a["debits"] - a["credits"]
        debit_bal = net if net > 0 else 0
        credit_bal = -net if net < 0 else 0
        total_debit += debit_bal
        total_credit += credit_bal
        accounts.append(
            {
                "code": a["code"],
                "name": a["name"],
                "type": a["type"],
                "debit_minor": debit_bal,
                "debit": _fmt(debit_bal),
                "credit_minor": credit_bal,
                "credit": _fmt(credit_bal),
            }
        )
    return {
        "as_of": as_of or "latest",
        "accounts": accounts,
        "total_debit_minor": total_debit,
        "total_debit": _fmt(total_debit),
        "total_credit_minor": total_credit,
        "total_credit": _fmt(total_credit),
        "balanced": total_debit == total_credit,
    }


async def _type_total(
    account_type: str, date_from: str | None = None, date_to: str | None = None
) -> tuple[int, list[dict]]:
    """Total for an account type on its normal side, plus per-account rows."""
    db = await get_db()
    conditions, params = ["a.type = ?", "a.is_archived = 0"], [account_type]
    if date_from:
        conditions.append("t.txn_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("t.txn_date <= ?")
        params.append(date_to)
    rows = await _rows(
        db,
        f"""
        SELECT a.code, a.name, a.normal_side,
               COALESCE(SUM(CASE WHEN l.direction = 'debit' THEN l.amount_minor ELSE -l.amount_minor END), 0) AS net_debit
        FROM accounts a
        JOIN entry_lines l ON l.account_id = a.id
        JOIN transactions t ON l.transaction_id = t.id
        WHERE {" AND ".join(conditions)}
        GROUP BY a.id ORDER BY a.code
    """,
        params,
    )
    items, total = [], 0
    for r in rows:
        a = dict(r)
        bal = a["net_debit"] if a["normal_side"] == "debit" else -a["net_debit"]
        total += bal
        items.append(
            {"code": a["code"], "name": a["name"], "balance_minor": bal, "balance": _fmt(bal)}
        )
    return total, items


async def profit_loss(date_from: str | None = None, date_to: str | None = None) -> dict:
    income_total, income = await _type_total("income", date_from, date_to)
    expense_total, expenses = await _type_total("expense", date_from, date_to)
    net = income_total - expense_total
    return {
        "period": {"from": date_from or "beginning", "to": date_to or "latest"},
        "income": income,
        "total_income_minor": income_total,
        "total_income": _fmt(income_total),
        "expenses": expenses,
        "total_expenses_minor": expense_total,
        "total_expenses": _fmt(expense_total),
        "net_profit_minor": net,
        "net_profit": _fmt(net),
    }


async def balance_sheet(as_of: str | None = None) -> dict:
    assets_total, assets = await _type_total("asset", date_to=as_of)
    liab_total, liabilities = await _type_total("liability", date_to=as_of)
    equity_total, equity = await _type_total("equity", date_to=as_of)
    income_total, _ = await _type_total("income", date_to=as_of)
    expense_total, _ = await _type_total("expense", date_to=as_of)
    earnings = income_total - expense_total
    equity_with_earnings = equity_total + earnings
    return {
        "as_of": as_of or "latest",
        "assets": assets,
        "total_assets_minor": assets_total,
        "total_assets": _fmt(assets_total),
        "liabilities": liabilities,
        "total_liabilities_minor": liab_total,
        "total_liabilities": _fmt(liab_total),
        "equity": equity
        + [
            {
                "code": "—",
                "name": "Current Earnings",
                "balance_minor": earnings,
                "balance": _fmt(earnings),
            }
        ],
        "total_equity_minor": equity_with_earnings,
        "total_equity": _fmt(equity_with_earnings),
        "equation_holds": assets_total == liab_total + equity_with_earnings,
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


async def get_audit_log(
    action: str | None = None, actor: str | None = None, limit: int = 25, offset: int = 0
) -> dict:
    db = await get_db()
    conditions, params = ["1=1"], []
    if action:
        conditions.append("action = ?")
        params.append(action)
    if actor:
        conditions.append("actor = ?")
        params.append(actor)
    where = " AND ".join(conditions)
    count = await _rows(db, f"SELECT COUNT(*) AS cnt FROM audit_log WHERE {where}", params)
    rows = await _rows(
        db,
        f"SELECT * FROM audit_log WHERE {where} ORDER BY seq DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return {
        "items": [dict(r) for r in rows],
        "total": dict(count[0])["cnt"],
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Writes — every mutation audits in the same DB transaction
# ---------------------------------------------------------------------------


async def create_account(
    code: str, name: str, account_type: str, description: str | None = None, actor: str = "mcp"
) -> dict:
    if account_type not in NORMAL_SIDE:
        raise ValueError(
            f"Invalid account type '{account_type}'. Must be one of: {', '.join(NORMAL_SIDE)}"
        )
    acct_id = _new_id("acc")
    now = _now()
    async with _write_lock:
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO accounts (id, code, name, type, normal_side, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    acct_id,
                    code,
                    name,
                    account_type,
                    NORMAL_SIDE[account_type],
                    description,
                    now,
                    now,
                ),
            )
            await _audit(
                db,
                actor,
                "create_account",
                "account",
                acct_id,
                f"Created account {code} · {name} ({account_type})",
            )
            await db.commit()
        except aiosqlite.IntegrityError as e:
            await db.rollback()
            raise ValueError(f"Account code or name already exists: {e}") from e
    return (await resolve_account(acct_id)) or {}


async def post_transaction(
    txn_date: str,
    description: str,
    lines: list[dict],
    reference: str | None = None,
    actor: str = "mcp",
    source: str = "mcp",
    audit_action: str = "post_transaction",
    audit_details: str | None = None,
) -> dict:
    """Post a balanced transaction. Each line: {account, direction, amount_minor, memo?}.

    audit_action/audit_details let callers (e.g. transfer_funds) record a single,
    correctly-labelled audit row instead of a second one.
    """
    if len(lines) < 2:
        raise ValueError("A transaction needs at least 2 entry lines")
    try:
        datetime.strptime(txn_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"txn_date must be YYYY-MM-DD, got '{txn_date}'") from e

    resolved = []
    debits = credits = 0
    for i, line in enumerate(lines, start=1):
        direction = line.get("direction")
        if direction not in ("debit", "credit"):
            raise ValueError(f"Line {i}: direction must be 'debit' or 'credit'")
        amount = line.get("amount_minor")
        # bool is a subclass of int — reject it explicitly so True can't post as 1 cent.
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError(f"Line {i}: amount_minor must be a positive integer (cents)")
        acct = await resolve_account(str(line.get("account", "")))
        if not acct:
            raise ValueError(f"Line {i}: account not found: {line.get('account')}")
        if acct["is_archived"]:
            raise ValueError(f"Line {i}: account {acct['code']} · {acct['name']} is archived")
        debits += amount if direction == "debit" else 0
        credits += amount if direction == "credit" else 0
        resolved.append((acct, direction, amount, line.get("memo")))

    if debits != credits:
        raise ValueError(
            f"Unbalanced transaction: debits {_fmt(debits)} != credits {_fmt(credits)}. "
            "Sum of debits must equal sum of credits."
        )

    txn_id = _new_id("txn")
    now = _now()
    async with _write_lock:
        db = await get_db()
        await db.execute(
            "INSERT INTO transactions (id, txn_date, description, reference, source, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (txn_id, txn_date, description, reference, source, now, actor),
        )
        for line_no, (acct, direction, amount, memo) in enumerate(resolved, start=1):
            await db.execute(
                "INSERT INTO entry_lines (id, transaction_id, account_id, line_no, direction, amount_minor, memo, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_new_id("line"), txn_id, acct["id"], line_no, direction, amount, memo, now),
            )
        await _audit(
            db,
            actor,
            audit_action,
            "transaction",
            txn_id,
            audit_details or f'Posted "{description}" · {_fmt(debits)} ({len(resolved)} lines)',
        )
        await db.commit()
    return (await get_transaction(txn_id)) or {}


async def transfer_funds(
    from_account: str,
    to_account: str,
    amount_minor: int,
    txn_date: str,
    memo: str | None = None,
    actor: str = "mcp",
) -> dict:
    src = await resolve_account(from_account)
    dst = await resolve_account(to_account)
    if not src:
        raise ValueError(f"Source account not found: {from_account}")
    if not dst:
        raise ValueError(f"Destination account not found: {to_account}")
    if src["id"] == dst["id"]:
        raise ValueError("Cannot transfer to the same account")
    description = f"Transfer: {src['name']} → {dst['name']}"
    # Delegate to post_transaction so the write + its single audit row are atomic.
    return await post_transaction(
        txn_date,
        description,
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
        audit_details=f"Transferred {_fmt(amount_minor)}: {src['name']} → {dst['name']}",
    )


async def reverse_transaction(txn_id: str, reason: str, actor: str = "mcp") -> dict:
    original = await get_transaction(txn_id)
    if not original:
        raise ValueError(f"Transaction not found: {txn_id}")
    if original["status"] == "reversed":
        raise ValueError(
            f"Transaction {txn_id} is already reversed (by {original['reversed_by_id']})"
        )
    if original["reverses_id"]:
        raise ValueError(f"Transaction {txn_id} is itself a reversal and cannot be reversed")

    contra_id = _new_id("txn")
    now = _now()
    # Date the contra at the ORIGINAL transaction's date so historical (as_of)
    # reports stay consistent: any snapshot that includes the original also
    # includes its reversal, instead of showing a reversed txn as still live.
    async with _write_lock:
        db = await get_db()
        await db.execute(
            "INSERT INTO transactions (id, txn_date, description, reference, reverses_id, source, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                contra_id,
                original["txn_date"],
                f"Reversal of: {original['description']} — {reason}",
                original.get("reference"),
                txn_id,
                "mcp",
                now,
                actor,
            ),
        )
        lines = await _rows(
            db,
            "SELECT account_id, line_no, direction, amount_minor, memo FROM entry_lines WHERE transaction_id = ? ORDER BY line_no",
            [txn_id],
        )
        for line in lines:
            ln = dict(line)
            flipped = "credit" if ln["direction"] == "debit" else "debit"
            await db.execute(
                "INSERT INTO entry_lines (id, transaction_id, account_id, line_no, direction, amount_minor, memo, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _new_id("line"),
                    contra_id,
                    ln["account_id"],
                    ln["line_no"],
                    flipped,
                    ln["amount_minor"],
                    ln["memo"],
                    now,
                ),
            )
        await db.execute(
            "UPDATE transactions SET status = 'reversed', reversed_by_id = ? WHERE id = ?",
            (contra_id, txn_id),
        )
        await _audit(
            db,
            actor,
            "reverse_transaction",
            "transaction",
            contra_id,
            f'Reversed "{original["description"]}" ({txn_id}): {reason}',
        )
        await db.commit()
    return (await get_transaction(contra_id)) or {}


# ---------------------------------------------------------------------------
# Raw query (read-only escape hatch)
# ---------------------------------------------------------------------------


# Whole-word match so legitimate identifiers like `created_at` (which contains
# "create") are NOT rejected. The read-only connection is the real guarantee;
# this is a clear, fail-fast second line of defence.
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


async def run_query(sql: str) -> list[dict]:
    stripped = sql.strip()
    if not (stripped.upper().startswith("SELECT") or stripped.upper().startswith("WITH")):
        raise ValueError("Only SELECT queries are allowed")
    forbidden = _FORBIDDEN_SQL.search(stripped)
    if forbidden:
        raise ValueError(f"{forbidden.group(1).upper()} is not allowed — read-only queries only")
    # Engine-enforced read-only connection (PRAGMA query_only=ON).
    db = await get_ro_db()
    rows = await _rows(db, sql)
    return [dict(r) for r in rows[:500]]
