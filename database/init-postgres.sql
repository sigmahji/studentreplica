\getenv application_password POSTGRES_APP_PASSWORD

CREATE ROLE studentreplica_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS PASSWORD :'application_password';
ALTER DATABASE studentreplica OWNER TO studentreplica_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO studentreplica_app;
