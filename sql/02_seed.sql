-- Publisher only (the analytics side receives these rows through the initial table sync).
INSERT INTO accounts (account_id, owner)
SELECT g, 'account-' || g FROM generate_series(1, 100) AS g
ON CONFLICT DO NOTHING;
GRANT SELECT ON accounts, ledger_entries TO cdc_user;
GRANT SELECT, INSERT ON accounts, ledger_entries TO app;
