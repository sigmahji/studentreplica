# StudentReplica

A Streamlit application with one private digital twin per account. Students can
record their studies, interests and achievements, receive an AI career assessment,
choose learning goals, and track a dated preparation plan.

The custom teal-and-coral logo is used in the header, sidebar and browser tab.
Its transparent background works with both appearance modes. See
[brand assets and design prompt](assets/BRANDING.md).

## Run

```powershell
cd D:\ST_Replica\studentreplica
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Create `.env` using the keys listed in `.env.example`. For live analysis, set
`ANTHROPIC_API_KEY` and an `AI_MODEL` identifier supported by your Anthropic account.
The supplied model name is a placeholder to verify with your provider. The optional
OpenAI provider uses `AI_PROVIDER=openai` and `OPENAI_API_KEY`.

Groq is also supported using its
[compatible API](https://console.groq.com/docs/openai). Set `AI_PROVIDER=groq`,
`GROQ_API_KEY`, and `AI_MODEL=openai/gpt-oss-120b` in `.env`. Requests use Groq's
endpoint, not the OpenAI service; the existing client library is reused. Keys
are never embedded in code, examples, prompts, or logs. Provider and model are
visible in the sidebar. The supplied local key is stored only in ignored `.env`.
Temporary provider errors use an offline example for that response only. The
configured live client is retained across saves and page reruns; the next uncached
AI request automatically retries it. Keep **Force mock AI** disabled for live analysis.
Groq's account limits still apply. Retryable requests honor a short `Retry-After`
delay; longer waits fall back to clearly labeled examples. Wait for the limit to
reset before requesting another live analysis. Fallback results are cached separately
from live results, and cached responses do not consume the local request allowance.
Prompt context uses compact JSON rather than indented JSON to reduce token usage
without changing student values. Provider token-limit (413), rate-limit (429) and
credential errors are distinguished in fallback notices without exposing raw
provider payloads. A saved offline example remains visible until analysis is refreshed.
**Reconnect AI** is available when initialization failed or credentials are missing;
restart Streamlit after changing `.env`.

Without working AI credentials, the app displays an offline banner and generates
deterministic examples. Offline examples are not live AI assessments.

## Local Market Research

With Groq configured, GPT-OSS browser search retrieves current public sources
automatically using the existing key. Only structured search/open tool results
are accepted, never URLs invented in the model's answer. See the
[Groq browser-search documentation](https://console.groq.com/docs/tool-use/built-in-tools/browser-search).
Set `TAVILY_API_KEY` to use an alternative recent search provider by city (or
university city), country, field, and target career. This alternative uses the
[Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search).
Restart Streamlit after changing environment configuration.

If live web search is unavailable and the student accepts remote work, the matcher
can fall back to the [Jobicy public job feed](https://github.com/Jobicy/remote-jobs-api).
Only listings explicitly marked Anywhere/Worldwide are considered, and results
retain their Jobicy link, publisher, publication date and seniority. Public records
are filtered locally, so no student information is sent to Jobicy. Retrieval is
cached per student/twin/day and is not automatically polled on reruns. This feed is
not evidence of local hiring demand or internship eligibility. A listing remains
unscored until the retrieved text supports specific required skills; mentioned
skills are not automatically treated as requirements. Local-only preferences
never receive remote fallback listings. Role references and location-based job
search links remain available even if both providers are unavailable.

The search provider receives a broad market query, not the student's name,
account ID, grades, conversation, or achievements. Search results are included as
untrusted evidence in the AI prompt. Sources, retrieval dates and available
publication dates appear in My Career Plan. Search results are leads, not a
guarantee that a vacancy remains open. Verify employer requirements and deadlines.

Without an available search provider, a location (or remote preference), or
usable evidence, the application explicitly
labels current local demand as unverified. Its 38 role profiles cover computing,
engineering, healthcare, business, law, education, science, arts, trades and other
fields. These are learning references, not advertised vacancies or real employers.
Custom and interdisciplinary fields are also supported by the AI planner.

## Student Workflow

The sidebar includes **Light** and **Dark** appearance modes. The dashboard opens
first, with hoverable progress charts for completed milestones, skills and academic
averages, a skill radar, recent activity and readable AI insight lists. Charts use
saved snapshots only; missing grades are not replaced with zero. Transitions respect
the operating system's reduced-motion preference. Custom degree, field, subject
and learning-skill inputs appear only after choosing **Other**.

1. Create an account or sign in. Existing accounts and their data are preserved.
2. In **Profile** enter study details, actual courses/grades, interests, location,
   expected graduation, earned skills/certificates, and desired skills.
3. Set free minutes after classes, employment, travel, sleep, and personal
   activities. Choose study days or allow AI to recommend from available days.
   Mark protected days and choose a planning horizon of 1-12 weeks.
4. Select **Save twin & analyze**. My Career Plan contains an academic/career
   assessment, alternative directions, gap options, an internship strategy and
   preparation before graduation. No employment outcome is guaranteed.
5. Confirm which suggested skills/achievements you have actually earned and which
   you want to pursue. Unconfirmed suggestions never become profile facts. Refresh
   the analysis after saving choices, or choose a career direction to replan.
6. Select **Use this roadmap** to adopt the proposed dates. Tasks exceeding free
   time or the graduation deadline are shown as deferred, never squeezed into
   protected time. Long tasks can be split across available days.
7. Record completed tasks with a note or evidence link. Refresh the analysis to
   incorporate progress and design the next cycle. Previous records remain in
   History, including when a new roadmap starts. Check-ins do not automatically
   increase skill proficiency or mark qualifications as verified.
8. Ask the academic/career coach about your direction, schedule or recent work.
   Conversation history belongs only to the signed-in student.

## Semesters And Learning

1. Choose a degree in **Profile**, or **Other** for a custom degree. Programs in
   healthcare, engineering, law, business, humanities and other fields have
   suggested subjects; every subject list also supports **Other**. Suggestions
   are not a claim about your university's official curriculum.
2. In **Semesters**, add each completed semester and optionally the current
   semester. Two semesters are allowed per study year: year 2 allows up to 4.
   A current semester must follow completed semesters; subjects currently in
   progress may have no final grade. Completed subjects require valid grades.
3. Select percentage, GPA or letter grading explicitly and identify core
   subjects. Semester edits retain other semesters, projects and progress.
   Earlier unassigned subject records remain available for manual assignment.
4. Weak core subjects and current coursework take priority in the roadmap.
   Advanced goals show known-weak or unverified prerequisites. Foundation
   tasks come before optional preparation and use the same free-time budget;
   work that does not fit is deferred, not added to protected days.
5. In **Learning**, choose **Free only** or **Free and paid**.
   Curated course/material links and official provider search links are
   labelled separately. Costs and certificate eligibility must be checked
   with the provider. Ask AI for a lesson or revision guidance at any time.
6. Add an actual chosen course/unit and its link. After reporting completion,
   AI generates five application-focused questions. Answers are graded by
   Python; **4 out of 5 (80%)** passes. Failed attempts identify concepts to
   revise and a new attempt generates a fresh quiz. Submitted attempts cannot
   be regraded or accessed from another account.
7. A live-AI pass adds dated formative assessment evidence, a conservative
   proficiency baseline and a progress milestone. Original university grades
   are never overwritten. Offline example quizzes are practice-only and
   cannot award assessed achievements. This is not a proctored exam,
   accredited certificate, professional license or proof of complete mastery.

## Jobs And CVs

**Jobs** extracts individual listings only when retrieved source
text supports them. Titles, skill requirements and evidence excerpts are checked
against that source; general portals remain source links, not fake vacancies.
Filters show strong coverage (70%+), around 60% coverage (50-69%), and interests.
Scores average recorded proficiency over required skills, with missing skills
counted as zero. A small explicit alias map handles names such as Python
programming/Python and Microsoft Excel/Excel; there is no opaque AI score.
Unknown requirements are unscored, not presented as a match.
Coverage is not a hiring probability. Emerging-skills advice includes evidence
links and confidence, or explicitly labels the market as unverified. Searches
are cached per student/twin/day; retrieval today does not establish posting age
or continued availability. Select a listing for your CV or add its gaps to your
learning goals.

**CV Studio** provides a configurable preview, AI relevance ordering, an optional
photo, clickable course evidence links, and genuine PDF/DOCX downloads. AI may
select only allowlisted fact IDs; the renderer copies actual twin records and
cannot insert generated employers, credentials or metrics. Passed formative
assessments are distinct from student-reported achievements. Sections/facts can
be included, removed and reordered; underlying facts are edited in the twin.
The Word document remains editable. Photos are size-limited, normalized to JPEG,
stripped of metadata and stored as private artifacts. They are never sent to AI;
**Remove CV photo** deletes this student's stored photo artifacts.

The calendar is a rolling plan, not a prediction of everything a student will
learn until graduation. Revisit it as grades, interests, availability and the
market change. Local licensing, accreditation and placement eligibility must be
checked for regulated professions. School students receive supervised exploration
guidance appropriate to their study level.

## Architecture

```text
Streamlit app.py
  -> UserContext(user_id)
  -> TwinRepository -> SQLite: account, twin, snapshots, chat, cache, artifacts
  -> AIService -> delimited prompts -> configured LLM -> JSON/Pydantic validation
               -> one repair attempt -> transparent offline fallback
  -> Career planner -> field/skill references -> local market evidence
                    -> AI direction and tasks -> deterministic dated scheduler
                    -> confirmed choices and recorded completion -> twin snapshot
```

The existing `modules` package names are retained. New planning functionality is
in `modules/career_planner.py`, `modules/market_research.py`, and
`modules/planning_ui.py`. Semester logic is in `modules/academics.py`, learning
and grading in `modules/learning.py`, and document rendering in
`modules/cv_exports.py`. Each has a separate UI module. No database migration
is needed: semester, course and progress records live in versioned twin JSON;
private quiz keys and photos use the existing user-filtered artifact store.

## Database And Accounts

The persistent database is `database/studentreplica.db`, using Python's built-in
SQLite engine through SQLAlchemy. No database server is needed. On first startup,
the previous `data/student_twin.db` is copied and integrity-checked automatically;
the original is retained. Existing accounts and all student records are preserved.
An existing destination is never overwritten or combined with another database.

```powershell
python -m storage.manage init
python -m storage.manage check
python -m storage.manage backup
```

Usernames are unique; passwords are stored only as salted PBKDF2 hashes. Each
account has its own validated UUID. Profiles, semesters, course assessments,
progress history, chat, AI caches, photos and generated CVs are user-filtered.
Logout clears widget state before another account signs in. SQLite transactions,
WAL mode and a busy timeout protect normal concurrent saves. Private database
files and backups are excluded from Git. See [database operations](database/README.md).

Student data reads/writes require a user context and are filtered by user ID.
AI caches include user ID, provider, twin version and prompt hash. Live research
results are cached per user/twin/day. Each analysis is saved with its source
evidence, twin version, provider and offline status. Logout clears widget state
so a second account cannot inherit the previous student's form entries. Logs use
event types, user IDs and error class names, not raw personal data.

Existing Twin Dashboard and History remain available. Historical grades and
self-reported work are retained separately from new assessment evidence.

## Verify

```powershell
python -m pytest -q
```

Tests cover account isolation and sign-in, exact AI prompt isolation, structured
outputs and fallback, multiple disciplines, evidence confirmation, protected
days, time budgets, task splitting, graduation cutoffs, progress history and an
end-to-end Streamlit onboarding/roadmap/check-in/logout workflow. Network calls
are mocked in tests, so tests do not spend AI or search credits.

Additional tests cover semester limits/current enrollment, explicit grade scales,
prerequisites, the exact 80% threshold, incomplete answers, repeated submissions,
cross-account quizzes/photos, source provenance, hybrid scoring, CV grounding,
image validation, PDF pagination, DOCX structure and the course-to-quiz UI.

Optional visual QA uses `tests/manual_browser_check.py` with Playwright, Edge
and pypdfium2 against a separate mock-only server on port 8510. Its synthetic
files go to ignored `data/qa_output/`, not into a student's records.
