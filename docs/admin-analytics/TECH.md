# Admin analytics implementation

Companion: [PRODUCT.md](PRODUCT.md). Setup, SQL examples, event conventions, and
operational limits: [README.md](README.md).

## Components

- `backend/analytics.py`: legacy `/track/pageview` plus bounded, versioned
  `/track/events`. New identity comes from live Supabase Auth, not unsigned JWTs.
  New metrics exclude all legacy rows.
- `frontend/src/analytics/RouteAnalytics.jsx`: route entry, navigation, auth
  transitions, visible-page heartbeat, and visibility return. Its shared event
  helper serializes session rotation with Web Locks when available. Session IDs
  use localStorage and a 30-minute rolling inactivity expiry. Storage denial
  falls back to tab memory; browsers without Web Locks have best-effort cross-tab
  concurrency. New event IDs deduplicate retries at the database, although this
  client makes only one delivery attempt.
- `backend/admin/routes.py`: live Auth plus the application-owned Commons role table;
  query CRUD with revisions, catalog, draft and saved execution. No product
  mutations or admin self-enrollment. API errors are sanitized.
- `backend/admin/query.py`: scoped SQL AST validation using pglast, safe
  functions/types/operators, approved views, AST parameter substitution, dedicated
  reader connection, read-only transaction, statement/lock deadlines, total
  execution cancellation, concurrency limits, and bounded streaming results.
  It rejects nested-CTE catalog escapes and nonrecursive CTE self-reference
  fallthrough. Parameters inside string literals are not rewritten.
- `frontend/src/admin/`: authenticated workspace, filters, saved-query editor,
  accessible results tables, SVG line/bar rendering, and response invalidation.
  Native SVG avoids adding admin chart dependencies to Fantasy's shared chart
  bundle. Auth and analytics route code are loaded asynchronously.

## Database boundary

`0083_analytics_workspace.sql` extends existing events and preserves old rows.
Event category is a PostgreSQL enum; namespaced `event_name` supports new product
counters without migrating the enum for every action. New envelopes carry UUID
identity, session and event IDs, server timestamps, and bounded JSON metadata.

Saved definitions are service-role-only with RLS enabled. A NOLOGIN
`commons_analytics_reader` is created for separate credential provisioning. It
has SELECT on reviewed views in the non-Data-API `analytics` schema. The views
intentionally expose restricted admin projections through their owner; they are
not for ordinary clients. No browser or reader receives raw auth table grants.
The executor requires this exact login name (or its pooler form) and rejects
superuser, role-creation, database-creation, or bypass-RLS capabilities.

A SELECT prefix is not a security boundary. The AST validator rejects writes,
modifying CTEs, SELECT INTO, locks, multiple statements, unapproved relations,
and functions/casts/operators outside the supported subset. Fresh connections
use a fixed `pg_catalog, analytics` search path and UTC. Read-only transactions
are an additional restriction. The AST renderer binds only parsed parameter
nodes, preserving quoted text and avoiding user-string interpolation.

`ANALYTICS_DATABASE_URL` never falls back to migration credentials or service
role. The runtime's Dice/Trips harness flags enforce the owned loopback port.
An absent connection disables query/catalog execution, without taking product
APIs, ingestion, or saved configuration offline. Connection failures produce
sanitized errors. See README for deployment provisioning.

Migrations remain in the Dice runner's existing analytics family. Its version
marker advances to 83; the shell check now includes analytics files when
calculating the latest version, matching the runner. Historical files remain
unchanged. The attestation checks required analytics objects and identity column.

## Metrics

Four seeded definitions use the common executor: distinct active users in range,
distinct visits and auth segments in range, daily active users, and daily auth
segments. Daily queries generate zero-filled UTC buckets for Commons, Dice,
Trips, Crowdset, and Fantasy. Range totals count distinct identities/sessions
rather than summing daily uniques. Logged-in/out sessions intentionally overlap.
`analytics.users` supports user-directory queries; product projections can be
added through reviewed migrations and catalog grants.

## Verification

Verified with synthetic data only:

- Backend suite in an isolated Python 3.12 environment: 1,394 passed, 53 skipped
  before the final two focused database regressions were added.
- Focused API/parser and real loopback database checks: 25 passed. The disposable
  database test creates its own database and reader role, verifies metrics across
  dates/auth transitions, legacy exclusion, zero days, truncation, denied direct
  writes/auth reads, and recovery after a failed query; then drops its fixtures.
- Frontend tests exercise anonymous access, SQL draft runs without saving,
  visualization persistence, filter-result invalidation, project mapping,
  session expiry, telemetry envelopes, and existing top-level routes.
- After design-system integration, the full frontend suite passes: 653 tests
  across 82 files. The route assertion now matches the merged gallery heading.
- Production frontend build and bundle checks pass using synthetic loopback
  configuration. Anonymous Fantasy's static closure is 182,045 gzip bytes JS and
  22,103 bytes CSS, within existing limits. No bundle budget was increased.
- Dice and Commons migration contract scripts pass.
- Browser inspection covers the real `/admin` sign-in page and the populated
  dashboard/editor with a temporary synthetic API fixture. The fixture is removed
  after verification; it is not a product auth bypass. SQL execution is verified
  separately against real loopback PostgreSQL. Screenshot evidence lives under
  `.dice-verification/admin-analytics/` and is not committed.

The standard Dice browser harness could not start: local default Python is 3.14,
while that launcher requires 3.12/3.13, and its default web ports were occupied.
No shared stack was reset or stopped. Full Google login, client telemetry through
real Supabase Auth/PostgREST, and a complete Dice game regression remain release
smoke checks. The database test uses a minimal synthetic Auth projection rather
than exercising all historical migrations against the managed hosted database.
No hosted operation or deployment has been performed.

## Follow-ups

Offline rollups, ETL, alternate storage, a visual query builder, user management,
retention/partitioning, scheduled exports, and richer BI features remain deferred.
Review query plans and online workload before expanding query scope. The public
collector is best effort telemetry rather than proof of a business action.

Final focused rerun: 25 API/parser/database tests passed, including actual
statement-timeout cancellation/recovery and AST parameter-literal preservation;
15 frontend analytics/product-route tests passed with the unrelated design
heading assertion excluded. Lint and migration checks pass. The temporary browser
fixture and both task-owned frontend servers have been removed/stopped.

## Merged design-system integration

Adopted PR #150 (`c63264dcadb77ce05183cb49a3119fc2c496387b`). Verified
the local DataPatterns component matches the merged version before integration.
The admin uses shared paper panels, button and form-control classes, Skeleton,
SegmentedControl for chart type, and DataRow for results and metric definitions.
Chart colours and rules use material tokens; custom CSS handles dashboard layout.
There are no taglines, decorative counters, comparison widgets, or showcase copy.

Initial loading uses the shared skeleton. Refresh retains chart data with a
concise status; changing SQL, revision, or filters clears mismatched results.
A stale request cannot replace the current response. Tests cover both retaining
data on refresh and saving the shared segmented selector's value.

Validation: five admin interaction tests pass, the complete frontend suite has
653 passing tests, lint and production build pass, and existing bundle budgets
remain intact (anonymous Fantasy: 182,067 gzip JS bytes, 22,103 CSS bytes). Browser
checks use synthetic API fixtures at desktop width and a 390px iframe viewport;
the dashboard and chart-type editor are functional. Desktop evidence:
`.dice-verification/admin-analytics/design-system-dashboard.png`. No deployment
or backend behaviour change was made for this integration. The one-time merge
monitor is paused because this follow-up is complete.

The follow-up palette uses dashboard-scoped overrides of existing `--paper` and
`--paper-light` tokens: off-white `#faf8f2` behind light cream `#fffdf8` panels.
The shared data-surface variable follows `--paper-light`. No global palette change
was made. The dashboard now uses SiteHeader with the mascot, Admin chart sticker,
and sign-out slot, with a separate main heading as other projects do. Five admin
interaction tests (including shared-header links), lint, production build, and
bundle checks pass. Synthetic browser evidence:
`.dice-verification/admin-analytics/cream-shared-header.png`.

Jason selected Warm sans from the button alternatives. The shared `.cc-button`
now uses `--sans` at 14px/600, normal tracking, and sentence-case labels; the small
variant uses 13px with its existing 44px target. Shape, material colours, shadows,
and interaction states remain shared. Admin inherits this directly without a
local typography override. Static and React design-system samples use sentence
case. Ten existing admin/design interaction tests, lint, production build and
bundle budgets pass. The real design gallery was inspected in the browser;
evidence: `.dice-verification/admin-analytics/warm-sans-shared-buttons.png`.

## PR validation checkpoint

Prepared from merged main in an isolated worktree. Full frontend suite: 653
passed; backend source suite: 1,394 passed and 55 environment-gated skips.
Focused API/parser/database/migration source checks: 27 passed, one database-gated
skip; the gated migration runner was then exercised separately on an owned
loopback database: all three checks passed, including fresh installation, repeat
run, and corrupted receipt rejection. Lint, build, bundle budgets, and migration
contract scripts pass. The CI Auth scaffold includes the user-directory fields,
CI opts into real analytics database tests, and migration assertions follow the
contract marker. The SQL fixture creates a temporary login without modifying an
existing reader password. Production provisioning, login/telemetry integration,
and deployment smoke checks remain separate from these local checks.

CI's media tests hit the physical free-space guard when using the runner's
`/tmp`, despite ample capacity on the workspace filesystem. The Crowdset job now
puts both pytest data and subprocess temporary files under `RUNNER_TEMP`, prints
both filesystem capacities, and checks the actual test filesystem before running.
Production limits and the admission guard are unchanged. Local full media suite:
275 passed, including physical-disk and storage-quota tests. Workflow YAML parses
correctly. No SDK cleanup or runner filesystem assumption is needed.
