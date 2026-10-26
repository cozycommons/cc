# Admin analytics

The frontend workspace is `/admin`. The shared backend owns `/admin/*` APIs and
`POST /track/events`. Coolify remains the infrastructure dashboard. All charts
execute online; there is no warehouse or processing job.

## Setup

Deploy the additive analytics migration through the normal release runner. It
creates a **NOLOGIN** reader role; enable login and set its password through a
trusted database console. Do not put the password in a migration or shell history:

```sql
ALTER ROLE commons_analytics_reader LOGIN;
```

In `psql`, use `\password commons_analytics_reader`. Configure only the backend:

```dotenv
ANALYTICS_DATABASE_URL=postgresql://commons_analytics_reader.PROJECT_REF:PERCENT_ENCODED_PASSWORD@SESSION_POOLER:5432/postgres?sslmode=require
```

Use the actual reader username required by your direct/pooler connection. Local
sandbox connections must use `commons_analytics_reader` and the harness's owned
loopback database port (Dice 54322; Trips 55322). Never use the migration account,
service-role credentials, or a hosted URL in a sandbox. Missing reader configuration
leaves event ingestion and product APIs running; charts return an unavailable error.

Grant `app_metadata.commons_admin: true` to the intended verified Supabase user
through a trusted server-side Auth Admin operation. Preserve its existing app
metadata. The dashboard checks live Auth on every request. `user_metadata` cannot
grant access, and Dice/Crowdset admin flags do not grant Commons access. Revoke by
removing this flag. No public endpoint assigns it.

Allow `https://cozycommons.dev/admin` as an Auth redirect. Deploy the shared
backend, shared frontend, **and Crowdset's separate frontend image**. The existing
SPA fallback already serves `/admin`; no infrastructure dashboard is embedded.
No production changes have been made by the implementation task.

## Metrics

- Active users: distinct verified authenticated account IDs with accepted events.
- Visits: distinct browser session IDs, shared across tabs when storage works,
  expiring after 30 minutes without reports. Hidden tabs do not send heartbeats;
  visible tabs report presence every five minutes, even without input.
- Logged-in/logged-out visit counts overlap if authentication changes. Do not
  sum them. Daily uniques also cannot be summed to get range uniques.
- Dates use UTC with an exclusive query end. Today's bucket is partial.
- Reliable metrics include only version-1 events. Legacy tracking remains
  queryable separately; it cannot establish verified identity or visit history.
- Client telemetry is best effort, can be blocked/spoofed, and is not an audit
  record. Storage denial falls back to tab-memory sessions. Without Web Locks,
  simultaneous cross-tab session creation can rarely split a visit.

The initial dashboard provides range active users/visits and their daily trends.
Every query uses the same editor, execution boundary, and chart renderer. The
schema catalog includes a minimal user directory without credentials or tokens.

## Add a product event

```js
import { trackEvent } from './analytics/events.js';
void trackEvent({
  project: 'dice',
  eventType: 'action',
  eventName: 'dice.game_created',
  metadata: { mode: 'ranked' },
});
```

The collector accepts event categories `pageview`, `search`, `activity`, and
`action`. New actions use namespaced `event_name` values; they do not require enum
changes. Metadata must be an object no larger than 4 KiB. Never include tokens,
freeform user content, email, or URL query parameters. Call this helper after an
operation succeeds; do not await it in the product's critical path.

The collector has an 8 KiB envelope cap, server receipt timestamps, UUID retry
idempotency, verified bearer identity, and a best-effort per-process limit of 300
reports/minute per direct peer. A reverse proxy can make that a shared limit;
configure edge abuse controls if deployment scale requires finer attribution.
The client makes one bounded attempt and keeps no durable queue.

## Queries and charts

Create a named SELECT, run it, choose table/line/bar, and save. X and optional
series columns name result columns; Y columns are comma-separated numeric result
columns. Give columns distinct aliases. Position orders cards. Running a draft
does not save it; Duplicate creates an unsaved copy. Revision checks prevent
silent overwrites by concurrent editors.

SQL parameters are `$1` (start timestamptz), `$2` (exclusive end timestamptz),
and `$3` (nullable project text). Cast parameters explicitly. Filters affect only
queries that reference them:

```sql
SELECT event_name, count(*) AS events
FROM analytics.events
WHERE created_at >= $1::timestamptz AND created_at < $2::timestamptz
  AND ($3::text IS NULL OR project = $3::text)
  AND event_type = 'action'
GROUP BY event_name
ORDER BY events DESC
```

Only approved `analytics.events`, `analytics.legacy_events`, and
`analytics.users` views are queryable. To add product data, add a reviewed
projection and SELECT grant in a forward migration, then extend `VIEWS` in
`backend/admin/query.py`. Review the view owner, fields, RLS boundary, and parser
function/type allowlists. Avoid blanket grants on current or future tables.
The views intentionally expose admin projections through their owner; ordinary
Supabase browser roles receive no schema access.

The AST validator accepts a restricted SELECT subset, including scoped CTEs,
joins, grouping, and supported built-ins; it is not full PostgreSQL compatibility.
It rejects arbitrary functions, casts, operators, modifying statements, and
unapproved relations. A separate reader login and read-only transaction enforce
another boundary. Each statement has a five-second timeout, execution has a
ten-second deadline after connection validation, and four queries can run at once.
Results cap at 1,000 rows, 50 columns, and 1 MiB, with truncation indicated.
Connection setup has a three-second connect timeout.

## Validation

```bash
RUN_ANALYTICS_DB_TESTS=1 PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_admin_analytics.py backend/tests/test_admin_analytics_db.py -q
cd frontend
npm test -- --run src/admin/Admin.test.jsx src/analytics/events.test.js src/App.test.jsx
```

The opt-in database test creates and drops a uniquely named database on loopback
54322 (or the dedicated localhost PostgreSQL service in GitHub Actions). It
creates its own temporary reader login and never changes an existing reader
password. It never loads dotenv or uses hosted credentials. See `TECH.md` for current validation evidence and limitations.
