"""Bootstrap a fresh OpenLedger SQLite database with the schema and sample data.

The chart of accounts and January transactions mirror the open-ledger.html demo;
later months add recurring activity so recent-date queries return data.

Usage:
    python scripts/seed.py                       # writes ./data/openledger.db
    OPENLEDGER_DB=/tmp/dev.db python scripts/seed.py

If the target DB already exists it is overwritten.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "scripts" / "schema.sql"
DB_PATH = Path(os.getenv("OPENLEDGER_DB", str(ROOT / "data" / "openledger.db")))

NORMAL_SIDE = {"asset": "debit", "expense": "debit",
               "liability": "credit", "equity": "credit", "income": "credit"}

ACCOUNTS = [
    ("1000", "Cash", "asset"),
    ("1010", "Bank", "asset"),
    ("1020", "Wallet A", "asset"),
    ("1030", "Wallet B", "asset"),
    ("1100", "Accounts Receivable", "asset"),
    ("2000", "Accounts Payable", "liability"),
    ("3000", "Owner's Equity", "equity"),
    ("4000", "Sales Revenue", "income"),
    ("5000", "Rent Expense", "expense"),
    ("5100", "Salaries Expense", "expense"),
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def fmt(minor: int) -> str:
    return f"${minor / 100:,.2f}"


def reset_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def audit(conn: sqlite3.Connection, actor: str, action: str, object_type: str,
          object_id: str | None, details: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (id, actor, action, object_type, object_id, details, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (new_id("aud"), actor, action, object_type, object_id, details, created_at),
    )


def seed_accounts(conn: sqlite3.Connection) -> dict[str, str]:
    by_code: dict[str, str] = {}
    now = "2026-01-01T08:59:00+00:00"
    for code, name, acct_type in ACCOUNTS:
        acct_id = new_id("acc")
        conn.execute(
            "INSERT INTO accounts (id, code, name, type, normal_side, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (acct_id, code, name, acct_type, NORMAL_SIDE[acct_type], now, now),
        )
        by_code[code] = acct_id
    audit(conn, "system", "seed", "ledger", None,
          f"Initialized chart of accounts ({len(ACCOUNTS)} accounts)", now)
    return by_code


def post(conn: sqlite3.Connection, by_code: dict[str, str], txn_date: str,
         description: str, reference: str, lines: list[tuple[str, str, int]],
         created_at: str, actor: str = "system") -> str:
    """Insert a balanced transaction. lines: [(account_code, direction, amount_minor)]."""
    debits = sum(a for _, d, a in lines if d == "debit")
    credits = sum(a for _, d, a in lines if d == "credit")
    assert debits == credits, f"unbalanced seed txn '{description}': {debits} != {credits}"
    assert len(lines) >= 2 and all(a > 0 for _, _, a in lines)

    txn_id = new_id("txn")
    conn.execute(
        "INSERT INTO transactions (id, txn_date, description, reference, source, created_at, created_by) "
        "VALUES (?, ?, ?, ?, 'seed', ?, ?)",
        (txn_id, txn_date, description, reference, created_at, actor),
    )
    for line_no, (code, direction, amount) in enumerate(lines, start=1):
        conn.execute(
            "INSERT INTO entry_lines (id, transaction_id, account_id, line_no, direction, amount_minor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id("line"), txn_id, by_code[code], line_no, direction, amount, created_at),
        )
    audit(conn, actor, "post_transaction", "transaction", txn_id,
          f'Posted "{description}" · {fmt(debits)} ({len(lines)} lines)', created_at)
    return txn_id


def reverse(conn: sqlite3.Connection, txn_id: str, reason: str,
            txn_date: str, created_at: str, actor: str = "system") -> str:
    desc, ref = conn.execute(
        "SELECT description, reference FROM transactions WHERE id = ?", (txn_id,)
    ).fetchone()
    contra_id = new_id("txn")
    conn.execute(
        "INSERT INTO transactions (id, txn_date, description, reference, reverses_id, source, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, 'seed', ?, ?)",
        (contra_id, txn_date, f"Reversal of: {desc} — {reason}", ref, txn_id, created_at, actor),
    )
    for account_id, line_no, direction, amount in conn.execute(
        "SELECT account_id, line_no, direction, amount_minor FROM entry_lines "
        "WHERE transaction_id = ? ORDER BY line_no", (txn_id,)
    ).fetchall():
        flipped = "credit" if direction == "debit" else "debit"
        conn.execute(
            "INSERT INTO entry_lines (id, transaction_id, account_id, line_no, direction, amount_minor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id("line"), contra_id, account_id, line_no, flipped, amount, created_at),
        )
    conn.execute("UPDATE transactions SET status = 'reversed', reversed_by_id = ? WHERE id = ?",
                 (contra_id, txn_id))
    audit(conn, actor, "reverse_transaction", "transaction", contra_id,
          f'Reversed "{desc}" ({txn_id}): {reason}', created_at)
    return contra_id


def seed_transactions(conn: sqlite3.Connection, by_code: dict[str, str]) -> None:
    # ── January 2026 — exactly the open-ledger.html demo data ──────────
    post(conn, by_code, "2026-01-01", "Opening balance — owner investment", "OPEN",
         [("1010", "debit", 5_000_000), ("3000", "credit", 5_000_000)], "2026-01-01T09:00:00+00:00")
    post(conn, by_code, "2026-01-02", "Fund Wallet A from Bank", "TRF",
         [("1010", "credit", 500_000), ("1020", "debit", 500_000)], "2026-01-02T10:15:00+00:00")
    post(conn, by_code, "2026-01-03", "Fund Wallet B from Bank", "TRF",
         [("1010", "credit", 300_000), ("1030", "debit", 300_000)], "2026-01-03T10:20:00+00:00")
    post(conn, by_code, "2026-01-05", "Transfer from Wallet A to Wallet B", "TRF",
         [("1020", "credit", 50_000), ("1030", "debit", 50_000)], "2026-01-05T14:30:00+00:00")
    post(conn, by_code, "2026-01-10", "Sale of services — invoice #1042", "INV",
         [("1000", "debit", 250_000), ("1100", "debit", 150_000), ("4000", "credit", 400_000)],
         "2026-01-10T11:00:00+00:00")
    post(conn, by_code, "2026-01-15", "Office rent — January", "BILL",
         [("5000", "debit", 120_000), ("1010", "credit", 120_000)], "2026-01-15T16:45:00+00:00")
    post(conn, by_code, "2026-01-22", "Accrued rent payable — co-working desks", "BILL",
         [("5000", "debit", 60_000), ("2000", "credit", 60_000)], "2026-01-22T09:30:00+00:00")
    post(conn, by_code, "2026-01-28", "Payroll — January salaries", "PAY",
         [("5100", "debit", 300_000), ("1010", "credit", 300_000)], "2026-01-28T18:00:00+00:00")

    # ── February–May 2026 — recurring monthly activity ─────────────────
    monthly_sales = {"02": 320_000, "03": 410_000, "04": 380_000, "05": 460_000}
    for month, sale in monthly_sales.items():
        inv = 1042 + int(month)
        post(conn, by_code, f"2026-{month}-08", f"Sale of services — invoice #{inv}", "INV",
             [("1010", "debit", sale), ("4000", "credit", sale)], f"2026-{month}-08T11:00:00+00:00")
        post(conn, by_code, f"2026-{month}-15", f"Office rent — month {month}", "BILL",
             [("5000", "debit", 120_000), ("1010", "credit", 120_000)], f"2026-{month}-15T16:45:00+00:00")
        post(conn, by_code, f"2026-{month}-28", f"Payroll — month {month} salaries", "PAY",
             [("5100", "debit", 300_000), ("1010", "credit", 300_000)], f"2026-{month}-28T18:00:00+00:00")

    # ── Recent activity (relative to today) ────────────────────────────
    today = datetime.now(timezone.utc)
    d = lambda days: (today - timedelta(days=days)).strftime("%Y-%m-%d")
    ts = lambda days: (today - timedelta(days=days)).isoformat()

    post(conn, by_code, d(9), "Customer payment received — invoice #1042", "RCPT",
         [("1010", "debit", 150_000), ("1100", "credit", 150_000)], ts(9))
    post(conn, by_code, d(6), "Sale of services — invoice #1101", "INV",
         [("1000", "debit", 180_000), ("4000", "credit", 180_000)], ts(6))
    post(conn, by_code, d(4), "Paid co-working accrual", "PAY",
         [("2000", "debit", 60_000), ("1010", "credit", 60_000)], ts(4))
    post(conn, by_code, d(3), "Transfer from Wallet B to Wallet A", "TRF",
         [("1030", "credit", 25_000), ("1020", "debit", 25_000)], ts(3))

    # A duplicate rent posting, then reversed — demonstrates contra postings.
    dup = post(conn, by_code, d(2), "Office rent — June (duplicate)", "BILL",
               [("5000", "debit", 120_000), ("1010", "credit", 120_000)], ts(2))
    reverse(conn, dup, "duplicate entry posted in error", d(1), ts(1))


def seed_settings(conn: sqlite3.Connection) -> None:
    now = "2026-01-01T08:59:00+00:00"
    conn.execute(
        "INSERT INTO org_settings (id, business_name, base_currency, created_at, updated_at) "
        "VALUES (1, 'OpenLedger Demo Co', 'USD', ?, ?)", (now, now),
    )


def verify(conn: sqlite3.Connection) -> None:
    """Loud failure if the seeded books don't balance."""
    debits, credits = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN direction='debit' THEN amount_minor END), 0), "
        "       COALESCE(SUM(CASE WHEN direction='credit' THEN amount_minor END), 0) FROM entry_lines"
    ).fetchone()
    if debits != credits:
        raise SystemExit(f"✗ seed produced unbalanced books: debits {debits} != credits {credits}")
    txns = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    accts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    audits = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    print(f"✓ {accts} accounts · {txns} transactions · {audits} audit rows")
    print(f"✓ books balance: total debits == total credits == {fmt(debits)}")


def main() -> None:
    if not SCHEMA_PATH.exists():
        raise SystemExit(f"schema not found at {SCHEMA_PATH} — run from repo root")
    print(f"→ resetting {DB_PATH}")
    conn = reset_db()
    try:
        by_code = seed_accounts(conn)
        seed_transactions(conn, by_code)
        seed_settings(conn)
        conn.commit()
        verify(conn)
    finally:
        conn.close()
    print(f"✓ seeded {DB_PATH}")


if __name__ == "__main__":
    main()
