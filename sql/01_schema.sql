-- Shared by the primary cluster and the analytics database.
CREATE TABLE IF NOT EXISTS accounts (
    account_id  integer PRIMARY KEY,
    owner       text        NOT NULL,
    currency    char(3)     NOT NULL DEFAULT 'ETB',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id      uuid PRIMARY KEY,
    txn_id        uuid        NOT NULL,
    account_id    integer     NOT NULL,
    direction     text        NOT NULL CHECK (direction IN ('debit', 'credit')),
    amount_cents  bigint      NOT NULL CHECK (amount_cents > 0),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ledger_entries_txn_idx     ON ledger_entries (txn_id);
CREATE INDEX IF NOT EXISTS ledger_entries_created_idx ON ledger_entries (created_at);
