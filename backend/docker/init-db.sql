-- Auto-runs on first Postgres container boot
-- Creates chr_user and grants all privileges on chr_db

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'chr_user') THEN
        CREATE USER chr_user WITH PASSWORD 'chr_password';
    END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE chr_db TO chr_user;
GRANT ALL ON SCHEMA public TO chr_user;