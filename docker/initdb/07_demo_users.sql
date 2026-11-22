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

-- The counter behind POST /sandbox mode mock: the example farms are handed out one after another (visitor k gets example farm
-- k modulo their number), so each visitor in a room gets another farm to work on (a copy; the example farm itself stays untouched).
CREATE TABLE IF NOT EXISTS app.sandbox_counter (
    id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    n  bigint   NOT NULL DEFAULT 0
);
INSERT INTO app.sandbox_counter (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
