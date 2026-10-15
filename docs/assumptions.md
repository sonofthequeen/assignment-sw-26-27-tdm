# Assumptions and policies

These are decisions the brief leaves open. Each is implemented as stated here; changing one
means changing the code reference given.

## Domain

| # | Assumption | Where |
|---|---|---|
| A1 | A **test** is one test day at one track **location**. Each actual **run** names the layout driven, which must be at that location. | `services/testing.py` |
| A2 | One **lap** is one traversal of the layout's `verified_length_m`: a skidpad circle, an acceleration attempt, or an autocross or endurance loop. | `models/laps.py` |
| A3 | A **planned run** may have any number of actual attempts. A run without a plan is "unexpected", and no placeholder plan is created. | `models/testing.py` |
| A4 | Changing a plan before execution is a *replacement*, so the original is kept. Deviations during execution are derived, not stored. Completing a plan is an explicit engineer decision, because runs record no outcome. | `services/planning.py` |
| A5 | Setup snapshots are append-only; a change is a new derived snapshot. | `models/setup.py` guard |
| A6 | Timing validity and physical completion are independent. An ABORTED attempt may still have completed the loop. | `models/laps.py` |
| A7 | **Mileage** counts one full verified layout for each physically completed lap, and zero for an incomplete lap. There is no partial distance. | `services/mileage.py` |
| A8 | The **fastest lap** comes from timed, timing-valid, completed FLYING laps, ranked by raw time plus penalty. | `models/laps.py` |
| A9 | Every physical tyre has a globally unique serial number. A tyre in a set has the set's compound. Mixed compounds within one run are allowed, and a compound filter matches a run if any fitted tyre uses that compound. | `models/tyres.py` |
| A10 | An objective's progress is the number of runs linked to it. Runs and objectives must belong to the same season. | `services/objectives.py` |
| A11 | Telemetry and log files live in external storage. The database indexes only their metadata, with one entry per distinct SHA-256. | `models/files.py` |

## Units and validation policy

Units are carried in field names. Plausibility limits are application policy in
`app/policies.py`, not physical constants and not database constraints:

| Value | Accepted range |
|---|---|
| Ambient temperature | −30.0 to 60.0 °C |
| Asphalt temperature | −30.0 to 90.0 °C |
| Tyre gauge pressure | greater than 0 and up to 400.0 kPa |
| Tyre surface temperature | −30.0 to 150.0 °C |
| Setup and alignment camber | ±10° |
| Setup and alignment toe | ±5° |

**Implied average lap speed** is checked against an upper limit per activity type:

| Activity | Upper limit |
|---|---|
| SKIDPAD | 25 m/s |
| ACCELERATION | 45 m/s |
| AUTOCROSS | 40 m/s |
| ENDURANCE | 40 m/s |
| GENERIC_TESTING | 50 m/s |

The check uses raw time and applies only to completed laps. There are no minimum speeds and
no global maximum lap time.

## Data

| # | Assumption |
|---|---|
| D1 | All seed and sample-CSV values are **synthetic**. The demo names start with `DEMO`/`Demo`, file URIs use the non-existent `demo://` scheme, and checksums are SHA-256 hashes of labels, not of real files. |
| D2 | Unknown values stay NULL. The system never fills in an engineering value it was not given. |
| D3 | SQLite is the assignment database. NUMERIC values are stored with REAL affinity and read back at their declared scale. PostgreSQL migration notes are in `data-model.md`. |
