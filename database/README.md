# StudentReplica Database

The Python backend lives in `storage/`, using SQLAlchemy. Local use defaults to
Python's built-in `sqlite3`; deployed apps can use hosted PostgreSQL through
Psycopg 3 by setting `DATABASE_URL`. The same account and user-isolated repository
operations are used for both databases.

- `studentreplica.db`: persistent application database, created automatically.
- `studentreplica.db-wal` / `studentreplica.db-shm`: SQLite-managed runtime files.
- `backups/`: private, consistent backups created by the command below.

All database files and backups are ignored by Git. They contain private records;
restrict access to this folder and do not publish it with a public web server.
SQLite is not encrypted at rest. Passwords are salted PBKDF2 hashes, never plaintext.

| Table | Stored data | Isolation key |
| --- | --- | --- |
| `accounts` | Unique username, hashed local password or disabled Google-only marker, display name | `user_id` primary key |
| `external_identities` | Google subject digest mapped to an account, no raw tokens/email | Unique provider/subject digest, indexed `user_id` foreign key |
| `twins` | Profile, skills, semesters, grades, courses, goals and progress | `user_id` primary key |
| `twin_snapshots` | Versioned history of that student's twin | Non-null indexed `user_id` |
| `chat_messages` | Private coach conversation | Non-null indexed `user_id` |
| `ai_cache` | Validated AI response cache | Unique `(user_id, cache_key)` |
| `generated_artifacts` | Insights, plans, quizzes, CV data and optional photo | Non-null indexed `user_id` |

## Initialize, Check And Back Up

Run from the project root:

```powershell
python -m storage.manage init
python -m storage.manage check
python -m storage.manage backup
```

The first default startup copies `data/student_twin.db` using SQLite's online
backup API, validates the copy and leaves the original untouched. Existing
accounts, password hashes, user IDs, semesters, snapshots, chat and artifacts are
preserved. An existing destination is never overwritten or merged. Custom
`DATABASE_URL` overrides remain separate and are not automatically imported.

## Isolation And Reliability

`accounts.user_id` and `twins.user_id` are primary keys. Usernames are unique and
normalized. Every student-owned table has a non-null `user_id`; repository reads,
writes and deletes use the explicit, validated UUID in `UserContext`. AI cache
keys also include this UUID. Logout clears the previous student's form state.

Connections enable write-ahead logging, full synchronous writes, foreign-key
enforcement and a 30-second busy timeout. Transactions commit together or roll
back on failure. Connection pools are keyed by database URL so a test/backup
database cannot silently replace the application's default connection.

Use registered accounts for persistent sign-in. Quick demo sessions deliberately
create a new isolated user each time and do not have reusable passwords. Browser
refresh may require signing in again, but saved records remain in the database.

To restore, stop Streamlit, retain a copy of the current database and its runtime
files, then restore the chosen backup as `studentreplica.db` before restarting.
Do not copy just an active `.db` file; use the backup command to include WAL data.

## Persistent Cloud Backend

Streamlit Community Cloud does not guarantee persistence of local files. Use a
dedicated managed PostgreSQL database for accounts and student data that must
survive application redeployments. See
[Streamlit's storage note](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).

Install the updated requirements, then put the provider's actual connection URL
in **Streamlit App settings > Secrets**:

```toml
DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
```

Alternatively, below the root-level AI secrets:

```toml
[database]
url = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
```

Keep database credentials out of Git and chat. URL-encode special characters in
the password when using a URL; use the provider's generated connection string.
Reboot the app after changing secrets. The application creates its tables
in the configured database and the sidebar identifies the active storage type.
Use a dedicated schema/database owned by the configured backend role, with
permission to create tables and enable row-level security. Verify the sidebar
says **Storage: PostgreSQL**, then create an account, save a profile, sign out
and back in, and confirm the records remain after an application reboot.

Row-level security is enabled on PostgreSQL student tables. The table owner
used by the Python backend can access them; no anonymous/browser policies are
created. Do not grant browser roles ownership, `BYPASSRLS`, or broad policies.
Application-level isolation still uses the authenticated `UserContext` on every
repository operation; this is not a direct browser-to-database API.

Remote connections default to TLS if no `sslmode` is supplied. The connection
pool checks for stale connections, uses bounded capacity, and disables automatic
prepared statements for compatibility with hosted poolers. SQL errors hide
bound student values. Connection failures stop the app with a private retry
message, never redirecting writes into a different database.

Existing local accounts and records remain in SQLite. Selecting PostgreSQL
does **not** automatically copy or merge them. Back up the local database and
plan an explicit administrator migration before moving existing students.
Enable your hosted provider's backups and retention settings. The SQLite backup
command does not export PostgreSQL; use provider backups or `pg_dump`.

## Local PostgreSQL Development

With Docker installed and strong, separate `POSTGRES_PASSWORD` and
`POSTGRES_APP_PASSWORD` values in the ignored `.env`:

```powershell
docker compose up --build -d
docker compose exec app python -m storage.manage check
```

Open [StudentReplica](http://localhost:8502). PostgreSQL is available only on
local port 5433 for database tools. `postgres_data` is a named volume preserving
records when containers are replaced. `docker compose down` keeps it; do not
use `down -v` unless intentionally deleting all database records after a backup.
The disabled TLS mode in Compose is only for its private local Docker network,
not public hosted databases. An initialization script creates a non-superuser
`studentreplica_app` role; the app receives only that role's password, never the
administrator password. The script runs only for a new PostgreSQL volume.
Changing environment password values does not automatically change passwords
in an already-initialized PostgreSQL volume; rotate them explicitly with an
administrator database connection.

## Editing The Backend

- `storage/models.py`: tables and constraints. Existing tables are not altered
  by `create_all`; schema changes require an explicit, reviewed data migration.
- `storage/repository.py`: user-filtered reads/writes; require `UserContext`.
- `storage/auth.py`: registration, password hashing and sign-in.
- `modules/google_auth.py`: native Google login, verified identity restoration and logout.
- `storage/database.py` / `storage/connections.py`: pools, transactions and setup.
- `storage/twin_schema.py`: the versioned JSON profile/academic/learning model.
- `storage/manage.py`: setup, health checks and local SQLite backups.

Install `requirements-dev.txt` and run `python -m pytest -q` after backend changes.
Real PostgreSQL isolation tests
run in `.github/workflows/backend-tests.yml` using synthetic students and a
temporary schema. Locally, set `TEST_POSTGRES_URL` to a **dedicated test database**
to enable them. Never use production credentials for test runs. Without that
setting the PostgreSQL integration test is explicitly skipped.
