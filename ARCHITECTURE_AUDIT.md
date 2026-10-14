# Architecture Audit - StudentReplica

**Date:** 2026-10-10  
**Scope:** Step 0 inspection of the current `studentreplica/` project before and during Phase 1 hardening.

## 1. What Exists

| Area | Current state |
| --- | --- |
| Framework | Streamlit. `app.py` is the UI entry point. |
| Main flow | Account gate, onboarding, twin dashboard, market matcher, CV studio, and history tabs. |
| Modules | `modules/digital_twin.py`, `modules/market_matcher.py`, and `modules/cv_generator.py` are still the feature modules. |
| Storage | Local SQLite or hosted PostgreSQL via SQLAlchemy in `storage/`, with `UserContext` required by repository methods that touch student-owned data. |
| User identity | Accounts create a UUID `user_id`; demo sessions also create fresh UUIDs. |
| Twin schema | Canonical in-memory dict shape in `storage/twin_schema.py`, persisted as JSON and versioned through snapshots. |
| AI layer | `ai/` already exists with provider clients, prompt templates, Pydantic schemas, service methods, validation, cache, rate limiting, and mock fallback. |
| Tests | Pytest tests exist for auth, repository behavior, isolation, AI schemas, AI service, and academic twin helpers. |
| Data | Runtime DB defaults to `database/studentreplica.db`; the former default is backed up into this location once. DB files are ignored by Git. |

## 2. Phase 1 Storage And Isolation Design

- `UserContext(user_id, session_id, created_at)` is the required scope object for student-data reads and writes.
- Student-owned tables include `user_id`: `twins`, `twin_snapshots`, `chat_messages`, `ai_cache`, and `generated_artifacts`.
- Repository queries filter by `ctx.user_id` or use `user_id` as the primary key.
- AI cache keys are now enforced to start with `<user_id>:` before read or write.
- Streamlit session state stores login/UI flags only. Student payloads such as twins and AI insight results are loaded from the repository by `user_id`.
- Chat history is stored per `user_id`; prompts are built from one loaded twin at a time.

## 3. Module-Level Or Global Mutable State

| Location | State | Assessment |
| --- | --- | --- |
| `storage.database` | `_engines`, `_initialized_engines`, `_engine_lock` | Connection pools keyed by database URL and initialization metadata/lock only; no student payloads. Overrides cannot replace the default connection. |
| `ai.service` | `_service_singleton` | Holds client and per-user rate-limit timestamps, not twin payloads. |
| `AIService._rate_windows` | Recent timestamps keyed by `user_id` | Acceptable operational metadata. |
| `MockClient.prompt_log` | Prompt payloads when enabled | Used for tests. App-created mock clients disable prompt recording to avoid process-level student payload retention. |
| `app.py` | `st.session_state` | `user_id`, auth/UI flags, selected job id only; no twin or AI result payload should be stored there. |

## 4. What Is Broken Or Risky

1. The Git working tree has many uncommitted changes from the interrupted Cursor run. I did not revert them.
2. Python requires the approved local runtime outside the restricted sandbox. Regression tests now run successfully there with temporary databases.
3. The reference catalog now contains 38 cross-discipline roles. Live browser search is separate; references never masquerade as vacancies.
4. CV generation now uses AI selection of allowlisted fact IDs, deterministic rendering, and genuine PDF/DOCX export.
5. `modules/cv_generator.py` retains legacy prompt helpers for compatibility. The active CV UI routes through `ai.service` and `modules/cv_exports.py` instead.
6. `.streamlit/config.toml.txt` is a harmless duplicate of `.streamlit/config.toml`; Streamlit will use `config.toml`.
7. Prompt payloads are saved with generated artifacts for explainability and isolation tests. They are scoped by `user_id`, but in production we may later want redacted prompt storage if privacy requirements tighten.

## 5. Places Data Could Mix If Future Code Is Careless

1. Any new repository method that queries a student-owned table without `ctx.user_id`.
2. Any future AI cache key that does not use `AIService._cache_key` or another `<user_id>:` prefix.
3. Any Streamlit feature that stores a full twin, AI response, prompt, chat message, uploaded document text, or generated CV directly in `st.session_state`.
4. Any global or singleton mock/debug logger that records raw prompts across users.
5. Any batch AI prompt that concatenates multiple students' twins.

## 6. Phase 1 Verdict

The current codebase has already moved beyond the original Phase 1 skeleton, but Phase 1's core contract is now explicit: all persisted student data is scoped by `user_id`, AI cache keys are user-prefixed, account/demo sessions create isolated UUIDs, and the UI reloads student payloads from the repository rather than keeping them in session state.

Database hardening adds a dedicated `database/` directory, consistent sqlite3
online backup/migration, read-only integrity checks, WAL/full synchronous writes,
30-second busy waits and canonical UUID validation. Explicit database overrides
no longer change the connection selected by later default requests. Database
files contain private data and are not encrypted at rest; filesystem access must
remain restricted. Password hashes and existing user IDs are preserved.

## 7. Semester And Learning Extension

- Semester records are stored in each student's versioned twin JSON. Two semesters per study year are validated in Python; current subjects may be ungraded, completed subjects may not. Earlier unassigned records remain separately available.
- Degree-specific subject/learning catalogs provide suggestions, not official university curricula. Custom degrees and subjects are retained.
- Academic recovery, current coursework and prerequisites are placed ahead of optional work. The deterministic scheduler still enforces free minutes, protected days and graduation cutoffs.
- Course records, completion reports, attempts and dated progress evidence belong to the twin. Quiz answer keys are private generated artifacts loaded by both `user_id` and assessment ID. A submitted attempt cannot be regraded. At least 80% is required; offline examples cannot award assessed proficiency.
- A passing quiz is formative evidence, not accreditation or a proctored mastery test. Historical university grades are never rewritten. AI factual accuracy and student identity during a quiz are not independently verified.
- Live market URLs come only from structured provider tool results. Opening titles, skill substrings and evidence quotations are checked against retrieved text. Retrieval does not prove a posting is recent or still open; source dates and uncertainty are displayed.
- CV exports contain selected literal twin facts. Photos are bounded, normalized, stripped of metadata and stored in private artifacts; removal is user-filtered. Photos are excluded from AI context and never written to shared export paths.
- PDF/DOCX bytes are generated per request in memory. Synthetic visual QA uses a separate database/server and ignored output directory; no real student records are used.

## 8. Cloud Backend Extension - 2026-10-14

- The same Python repositories and authentication support PostgreSQL through
  Psycopg 3 and a private `DATABASE_URL`. SQLite remains the local default.
- Remote PostgreSQL defaults to TLS; bounded pools check stale connections and
  disable prepared statements for transaction pooler compatibility.
- PostgreSQL tables enable row-level security without browser policies. The
  backend owns its tables; per-student isolation remains enforced in Python.
- Docker Compose creates a non-superuser app role and a persistent PostgreSQL
  volume. Administrator credentials are not passed to the app container.
- Startup errors hide connection details and never silently redirect writes to
  SQLite. Existing local records are not automatically migrated or merged.
- Verified a fresh Python 3.14 dependency installation and 170 passing tests.
  The live PostgreSQL test was skipped locally because no server is available;
  a GitHub workflow is configured to run it against a temporary test schema.
- No hosted database has been provisioned. Cloud activation requires a dedicated
  PostgreSQL connection in Streamlit Secrets; local files are not durable cloud
  storage. Backend setup, schema-change and backup guidance is in `database/README.md`.
