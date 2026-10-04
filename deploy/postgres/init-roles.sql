-- Only a newly initialized, dedicated database or an owner-authorized upgrade.
-- psql reads secret values from the process environment; never echo queries.
\getenv runtime_password SSO_RUNTIME_PASSWORD
\getenv migrator_password SSO_MIGRATOR_PASSWORD
SELECT format('CREATE ROLE sso_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L', :'runtime_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sso_runtime') \gexec
SELECT format('CREATE ROLE sso_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sso_migrator') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO sso_migrator;
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO sso_runtime, sso_migrator', current_database()) \gexec
GRANT USAGE ON SCHEMA public TO sso_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sso_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sso_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE sso_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sso_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE sso_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sso_runtime;
