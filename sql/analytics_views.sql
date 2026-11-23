-- Analytics-only objects. Fed by logical replication, so never written to directly.
CREATE OR REPLACE VIEW account_balances AS
SELECT account_id,
       COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'credit'), 0)
     - COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'debit'),  0) AS balance_cents,
       COUNT(*) AS entries
FROM ledger_entries
GROUP BY account_id;

CREATE OR REPLACE VIEW entries_per_minute AS
SELECT date_trunc('minute', created_at) AS minute, COUNT(*) AS entries
FROM ledger_entries
GROUP BY 1
ORDER BY 1;
