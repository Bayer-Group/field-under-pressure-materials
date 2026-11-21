-- User accounts of the demo API: a login and a password (schema app). Safe to run more than once; also applied to an existing database by
-- docker/migrations/010_user_accounts.sql. Not real authentication: a mock for switching between users (scrypt password hashes, a signed
-- token, isolation by owner_id on the server); a production system would use OIDC. Separate from app.demo_user, the logins of the example
-- farmers (farmer001 ...), which the mock data generator deletes and recreates and which are read-only: the accounts here own farms that can
-- be edited, and are never touched by it. Filled by scripts/generate_user_accounts.py and by POST /register.

CREATE TABLE IF NOT EXISTS app.user_account (
    account_id    bigserial PRIMARY KEY,
    login         text NOT NULL,
    password_hash text NOT NULL,                              -- scrypt$n$r$p$salt$hash (backend/app/core/security.py)
    owner_id      text NOT NULL,                              -- matches app.field.owner_id: the farms of this account
    role          text NOT NULL DEFAULT 'farmer' CHECK (role IN ('farmer', 'analyst')),
    display_name  text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_account_login_key UNIQUE (login),
    CONSTRAINT user_account_owner_key UNIQUE (owner_id),
    CONSTRAINT user_account_login_format CHECK (login = lower(login) AND login ~ '^[a-z0-9][a-z0-9._-]{2,29}$'),
    CONSTRAINT user_account_owner_not_sandbox CHECK (owner_id NOT LIKE 'sbx-%')
);
COMMENT ON TABLE app.user_account IS 'Login and password accounts of the demo API (a mock, not real authentication); owner_id links an account to its farms';
