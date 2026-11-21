-- Demo users of the API (schema app). Safe to run more than once; also applied to an existing database by
-- docker/migrations/005_demo_users.sql. A demonstration login only (hashed passwords, signed token, isolation by owner_id on the
-- server); a production system would use OIDC. Filled by scripts/generate_mock_farmers.py.

CREATE TABLE IF NOT EXISTS app.demo_user (
    login         text PRIMARY KEY,
    password_hash text NOT NULL,                              -- scrypt$n$r$p$salt$hash (backend/app/core/security.py)
    owner_id      text NOT NULL,                              -- matches app.field.owner_id
    role          text NOT NULL DEFAULT 'farmer' CHECK (role IN ('farmer', 'analyst')),
    display_name  text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS demo_user_owner_idx ON app.demo_user (owner_id);
