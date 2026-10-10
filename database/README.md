# StudentReplica Database

The app uses Python's built-in `sqlite3` engine through its existing SQLAlchemy
repository. No separate database server or installation is required.

- `studentreplica.db`: persistent application database, created automatically.
- `studentreplica.db-wal` / `studentreplica.db-shm`: SQLite-managed runtime files.
- `backups/`: private, consistent backups created by the command below.

All database files and backups are ignored by Git. They contain private records;
restrict access to this folder and do not publish it with a public web server.
SQLite is not encrypted at rest. Passwords are salted PBKDF2 hashes, never plaintext.

| Table | Stored data | Isolation key |
| --- | --- | --- |
| `accounts` | Unique username, salted password hash, display name | `user_id` primary key |
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
