-- OpenLedger schema — double-entry accounting warehouse.
-- Money is INTEGER minor units (cents). Transactions and entry lines are
-- immutable: corrections happen via contra postings (reverse_transaction).

CREATE TABLE accounts (
  id          TEXT PRIMARY KEY,
  code        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
  type        TEXT NOT NULL CHECK (type IN ('asset','liability','equity','income','expense')),
  normal_side TEXT NOT NULL CHECK (normal_side IN ('debit','credit')),
  description TEXT,
  is_archived INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX idx_accounts_type ON accounts(type);
CREATE INDEX idx_accounts_archived ON accounts(is_archived);

CREATE TABLE transactions (
  id             TEXT PRIMARY KEY,
  txn_date       TEXT NOT NULL,                -- ISO date (YYYY-MM-DD)
  description    TEXT NOT NULL,
  reference      TEXT,
  status         TEXT NOT NULL DEFAULT 'posted' CHECK (status IN ('posted','reversed')),
  reverses_id    TEXT REFERENCES transactions(id),  -- set on the contra transaction
  reversed_by_id TEXT REFERENCES transactions(id),  -- the only field ever updated, set once
  source         TEXT NOT NULL DEFAULT 'mcp' CHECK (source IN ('api','mcp','ui','seed','import')),
  created_at     TEXT NOT NULL,
  created_by     TEXT NOT NULL,
  CHECK (reverses_id IS NULL OR reverses_id != id)
);
CREATE INDEX idx_txn_date ON transactions(txn_date);
CREATE INDEX idx_txn_status ON transactions(status);

CREATE TABLE entry_lines (
  id             TEXT PRIMARY KEY,
  transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
  account_id     TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  line_no        INTEGER NOT NULL,
  direction      TEXT NOT NULL CHECK (direction IN ('debit','credit')),
  amount_minor   INTEGER NOT NULL CHECK (amount_minor > 0),
  memo           TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE (transaction_id, line_no)
);
CREATE INDEX idx_lines_account ON entry_lines(account_id, transaction_id);
CREATE INDEX idx_lines_txn ON entry_lines(transaction_id);

CREATE TABLE audit_log (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  id          TEXT NOT NULL UNIQUE,
  actor       TEXT NOT NULL,
  action      TEXT NOT NULL,                   -- create_account, post_transaction, transfer_funds, reverse_transaction, seed
  object_type TEXT NOT NULL,
  object_id   TEXT,
  details     TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_audit_action ON audit_log(action);

CREATE TABLE org_settings (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  business_name TEXT NOT NULL,
  base_currency TEXT NOT NULL DEFAULT 'USD',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
