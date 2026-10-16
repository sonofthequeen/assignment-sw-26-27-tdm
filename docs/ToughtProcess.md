# Thought Process

This document explains the choices made while completing the Test Data Manager assignment, and
why those choices were appropriate. The [README](../README.md) covers how to run the system;
this file covers *why* it looks the way it does.

## 1. Reading the problem

The brief describes a team losing engineering history in spreadsheets. I read its real
requirement as **trustworthy history**: being able to say later what was planned, what
actually ran, with which setup and tyres, in what conditions, how fast, and how far, and to
query all of that across seasons.

Two phrases set the priorities:

- "**Historical Querying** is the paramount reason", so the multi-filter run search had to be
  correct and complete before anything else counted as done.
- "**not a simple CRUD application**", so integrity, derivation and traceability matter more
  than the number of endpoints.

The brief also says partial delivery is acceptable and that design reasoning is the focus.
Given a deadline of roughly one week, I chose a narrow, complete and tested slice over a broad,
shallow one.

## 2. Scope strategy

Every capability was classified before any code was written:

- **MVP-Core:** the season → test → run → lap chain, planned versus actual, setups, laps,
  mileage and search.
- **MVP-Complete:** tyres, objectives, the file index, the importer, the frontend, Docker and
  CI.
- **Extended:** stations and sectors.
- **Deferred:** corrections, partial distance and authentication.

Each phase ended with its tests passing before the next started.

Two decisions mattered most here:

- **Tyres were added before the seed and the importer** (a dedicated "6.5" phase). Otherwise
  the demo data and the CSV format would have had to be rewritten once tyres existed.
- **Setup-performance statistics and stations were dropped deliberately.** They would have
  competed with the required deliverables: the importer, the containerised setup, and the
  frontend.

## 3. Domain boundaries and the hierarchy

The modules are reference data, tracks, testing (tests, planned runs, runs), setup, laps,
tyres, objectives and files. Dependencies flow one way: routers → services → models. Read-only
compositions live in `queries/`.

**Test and Run are separate entities.** A test is a day at a **track location**, as the brief
says. Each run records the **layout** actually driven, because one day often mixes skidpad and
autocross. "A run's layout must be at its test's location" is a cross-row rule, checked in the
service layer. Enforcing it in the database would have meant denormalising the location onto
`run`, duplicating data that could then disagree.

## 4. Planned versus actual

This is the most important modelling decision. A planned run and an actual run are
**different facts**: an intention and an observation. Overwriting one with the other destroys
exactly the information the brief asks for, namely what was modified, what was cancelled, and
what was added unexpectedly. So:

- **Plans are never edited.** They change only through named commands, and every command keeps
  the original values and records a reason:
  - *cancel*;
  - *replace*, which creates a new plan and links it to the original, atomically;
  - *complete*.
- **One plan has 0..N actual runs.** An aborted attempt followed by a retry is common on test
  days. Making the link one-to-one would have forced a fake plan or a lie.
- **An unexpected run has no plan.** A placeholder plan would pollute every "planned versus
  actual" count.
- **"Modified" is derived, not stored.** The comparison endpoint reports, per aspect (driver,
  layout, setup, control map, lap count, target time), whether it matched, differed, or cannot
  be compared. Absent data is never treated as a mismatch.
- **Completion is an explicit decision.** No run outcome is modelled, so the mere existence of
  a run does not prove that the plan was achieved.

## 5. Setups: typed snapshots, append-only

I compared three ways to store setups:

| Option | Assessment |
|---|---|
| Fully typed tables | Chosen |
| Typed core plus a constrained parameter-definition extension | Kept for later |
| JSON or unrestricted EAV | Rejected: it gives up validation, queryability and readable history |

The typed design keeps whole-vehicle values as columns, and corner values as one row per
FL/FR/RL/RR, which avoids a 40-column table. Missing corners stay absent instead of being
defaulted.

A **snapshot never changes.** A setup change is a new snapshot `derived` from its source, with
a required reason and a timestamp, and runs reference whichever snapshot they used. "What
changed since the previous setup" is a **computed diff**, so it cannot drift out of sync.

Immutability is enforced in two ways:
- there is no update API;
- a SQLAlchemy `before_flush` guard rejects mutation from *any* code path, including seed and
  import.

I deliberately did not use database triggers. The guard is simple, tested and portable. Raw
SQL can bypass it, and that is documented.

Observed alignment is a separate table, because the **intended** setup and **measured** values
are different facts.

## 6. Tyres and measurements

Every physical tyre has a globally unique serial number. A tyre belongs to a compound, and
optionally to a set.

**A tyre's compound cannot contradict its set's compound.** This is a database invariant
without a trigger: a composite foreign key `(tire_set_id, compound_id)` points at
`UNIQUE(id, compound_id)` on `tire_set`.

**Fitment** is keyed by run and corner, with `UNIQUE(run, tire)` so one tyre can't occupy two
corners. A **measurement** references the fitment through a composite foreign key, so a corner
with no fitted tyre cannot be measured. It is therefore always known which physical tyre a
pressure belongs to.

**Mixed compounds** within a run are allowed. The search's compound filter means "at least one
fitted tyre uses that compound", which is documented.

## 7. Laps: validity, completion, effective time, mileage

Spreadsheets tend to merge two different questions: "does this time count?" and "did the car
drive the loop?" I kept them separate:

| Concept | Rule |
|---|---|
| `timing_valid` | Can this time be ranked? An invalid lap needs a reason. |
| `physically_completed` | Did the car cover the verified layout length? |
| Untimed lap | `raw_time_ms` may be null (for example a transponder miss); the database then forces it to be timing-invalid |
| Effective time | `raw + penalty`. Penalties change ranking, not distance. |
| Fastest lap | Timed, timing-valid, completed FLYING laps only, with a deterministic tie-break |
| Mileage | Each physically completed lap counts one verified layout length, regardless of validity, penalty or classification. Incomplete laps count zero. |

**ABORTED is deliberately not tied to "incomplete".** A driver can abandon a push lap and
still drive back round. **No partial distance is invented**, because there is no verified
source for it.

**These values are `hybrid_property`s, not stored columns.** That way the API, the rankings and
the SQL aggregates share one definition. A test checks that the Python and SQL versions agree
for every combination of inputs. Nothing derivable is stored, so nothing can drift out of sync.

**Plausibility** is an *application* policy: an upper limit on implied average speed per
activity type, applied to raw time on completed laps. A global maximum lap time in the
database would have been arbitrary, and wrong for some activity.

## 8. Historical search and query design

`GET /runs` takes 16 filters combined with AND. The design choices:

- **Joins are to-one only:** run → test → layout, with a LEFT JOIN to conditions. Duplicates
  are therefore impossible, and the count uses the same joins as the page.
- **Laps are never joined into the filter.** Lap statistics for a page come from one grouped
  query, and the fastest lap per run from one `ROW_NUMBER()` window query.
- **The tyre compound filter is a correlated EXISTS**, so four matching corners never produce
  four rows.
- **A page costs four SQL statements whatever its size.** This is asserted by a test.
- **Missing conditions have explicit semantics.** Runs without a temperature are excluded only
  when that temperature is filtered.
- **Inverted ranges are rejected, never swapped.**
- **Unknown query parameters return 422**, because a mistyped filter that silently returned
  all history would be dangerous.

**Indexes were added only where an implemented query needed them**, and EXPLAIN QUERY PLAN
confirmed each one. That gives five explicit indexes. Where a scan is cheap at this data
volume, for example the `planned_run_id` filter, that is documented, together with the index
to add first if volume grows.

## 9. Transactions and errors

- **One session and one transaction per request.** Services flush but never commit, so a
  multi-row command (a lap batch, a replacement, a derivation, a four-corner fitment) is
  atomic. Tests inject failures to prove it.
- **Errors have one shape**, `{error: {code, message, details[{field, issue}]}}`:
  - 404 when the path resource doesn't exist;
  - 409 for conflicts and state violations;
  - 422 for validation and domain rules.
- **Database IntegrityErrors are translated through a registry keyed by constraint name.**
  SQLite reports UNIQUE failures by column, so those are mapped back to constraint names
  through the ORM metadata. No SQL, table name or stack trace ever reaches a client.

## 10. Migrations and SQLite

The migrations are hand-reviewed Alembic revisions: `0001` is the core, and `0002`, `0003` and
`0004` are additive. There is a naming convention for every constraint, and batch mode is used
for SQLite. Tests compare the migrated schema with the ORM (including CHECK constraints, which
Alembic ignores), upgrade databases that already contain data, and downgrade them.

SQLite was the right choice for an assignment that must run anywhere, but it has costs:

- NUMERIC is stored as REAL, so sums are done in Python `Decimal`.
- Timestamps are stored naive and normalised to UTC by a type decorator.
- DDL is not transactional.
- Rebuilding a table referenced by foreign keys needs SQLite's documented foreign-key
  procedure.

[data-model.md §8](data-model.md) describes the path to PostgreSQL: `timestamptz`, exact
NUMERIC, native ENUMs, CHECKs that SQLite couldn't add without a table rebuild, and generated
columns.

## 11. Import and seed

**The importer** accepts one documented canonical format, rather than guessing at arbitrary
spreadsheets:

- Normalisation is strictly cosmetic: whitespace, case, boolean spellings.
- Reference data is **looked up, never created**, because a layout's length must be verified.
- Every row error is reported with its row, field and code.
- The **whole file is atomic**.
- **Dry run is the default.** It executes the real write path through the domain services and
  then rolls back, so it reports exactly what a commit would do.
- Re-importing the same file creates nothing.

**The seed** is built through the same services as the API, so it obeys every rule. It runs in
one transaction, and a marker record makes repeat runs safe. It covers every scenario the
system distinguishes, and its values are clearly labelled synthetic.

## 12. Frontend scope

The frontend exists to *demonstrate* the backend, not to duplicate it:

- a dashboard;
- the historical browser, where filters sync to the URL and filtering and pagination are done
  by the backend;
- test, run and setup views;
- one complete write workflow (create a test).

Everything else (logging laps, corrections) was deliberately left out rather than built as
non-functional forms. It uses TypeScript in strict mode with types copied from the OpenAPI
schema, a small `fetch` client with typed errors, sections that load and fail independently,
and text badges so colour is never the only signal.

## 13. Testing strategy

**Backend: 508 tests**, each run against its own copy of an Alembic-migrated SQLite file. They
assert behaviour, not just status codes:
- exact mileage;
- fastest-lap ranking and tie-breaking;
- that rollback leaves tables untouched;
- that constraint names appear in errors;
- query counts;
- that the ER diagrams match the ORM.

**Mutation checks.** I temporarily broke critical rules, confirmed that tests failed, then
restored the files and verified them by hash. The rules included:
- the eligibility filter;
- the mileage filter;
- bulk atomicity;
- the immutability guard;
- the plan-state check;
- dry-run persistence;
- EXISTS replaced by a join.

**Frontend: 24 workflow-level tests** against a mocked `fetch`.

**Python 3.12 is verified** by running the full suite in a `python:3.12-slim` container.

## 14. Defects worth mentioning

Several real defects were caught by tests, audits or the review, not by reasoning alone:

1. **FastAPI's default scope for yield dependencies commits *after* the response is sent.** A
   failed commit would therefore have reached the client as a 201 for data that was never
   saved. The fix is `scope="function"`, and a test injects a commit failure to prove it.
2. **Autogenerated migrations imported application types** (`0001`, `0004`), which would have
   broken them later. Fixed by hand review.
3. **`alembic.ini`'s default path separator split `C:\` paths.** Caught because warnings are
   treated as errors in the tests.
4. **Downgrading a table referenced by foreign keys failed under foreign-key enforcement.**
   Fixed by following SQLite's documented procedure in `env.py`, with an integrity check
   afterwards.
5. **A create response echoed the client's time offset, while reads returned UTC.** Fixed by
   normalising to UTC at the request boundary.
6. **A composite foreign key made the ORM synchronise a column through two paths.** Fixed by
   making the navigation relationship view-only.
7. **The visual review at 390 px found table cells breaking dates and times mid-value.**
   Fixed by keeping cells on one line inside the scrolling table container.

## 15. Known limitations and what comes next

**Honest limitations:**
- Create-once records cannot be corrected.
- There is no authentication.
- SQLite allows one writer at a time.
- The importer accepts a single format.
- Search uses offset pagination.
- The UI has one write flow.

**Next, in this order:**
1. Explicit correction records, which supersede an earlier value instead of mutating it.
2. Authentication and roles.
3. PostgreSQL.
4. Setup-performance statistics, with sample-size caveats.
5. Run-to-previous-run setup history.
6. Test-day stations, and sector times.
7. UI flows for logging runs and laps.
