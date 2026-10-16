-- Read-only reporting role for Power BI Desktop (run as a database owner / superuser).
-- The password is supplied at run time; it is never stored in this repository:
--   psql -d plantops -v bi_password="'choose-a-strong-password'" -f docs/powerbi/create_bi_reader.sql
-- The role can read ONLY the curated views in schema "bi". Views run with their owner's
-- privileges, so no grant on the application tables (users, audit log, contact data) is needed.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'plantops_bi_reader') THEN
    CREATE ROLE plantops_bi_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END $$;

ALTER ROLE plantops_bi_reader PASSWORD :bi_password;
ALTER ROLE plantops_bi_reader SET default_transaction_read_only = on;
ALTER ROLE plantops_bi_reader SET statement_timeout = '120s';
ALTER ROLE plantops_bi_reader CONNECTION LIMIT 10;

REVOKE ALL ON SCHEMA public FROM plantops_bi_reader;
SELECT format('GRANT CONNECT ON DATABASE %I TO plantops_bi_reader', current_database()) \gexec
GRANT USAGE ON SCHEMA bi TO plantops_bi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA bi TO plantops_bi_reader;
-- Views created by later migrations become readable automatically:
ALTER DEFAULT PRIVILEGES IN SCHEMA bi GRANT SELECT ON TABLES TO plantops_bi_reader;
