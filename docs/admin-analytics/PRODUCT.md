# Cozy Commons admin analytics

## Summary

Provide a private analytics workspace at `https://cozycommons.dev/admin` for
understanding users, project usage, and product activity. Start with active users
and logged-in/logged-out visits per project, backed by live Supabase queries.
Coolify continues to own deployment, runtime logs, and infrastructure operations.

Status: implemented locally; production provisioning and deployment remain separate.

## Design

The workspace uses the reusable components and material tokens merged in
[design-system PR #150](https://github.com/cozycommons/cc/pull/150).
Keep the dashboard simple: functional labels, compact controls, and no taglines
or unnecessary instructions. Reuse components without adding showcase-only UI.
Buttons use the shared Warm sans style: existing sans font, 14px semibold,
sentence case, and raised surfaces, as chosen by Jason.
Use the shared SiteHeader with the Admin product icon and account controls.
The workspace scopes the existing paper tokens to off-white (`#faf8f2`) and
light cream panels (`#fffdf8`); other projects retain their existing palette.
Design integration preserves the analytics behavior and query boundary.

No mock supplied. Follow `docs/crowdset/DESIGN.md`: concise labels, restrained
layout, and no taglines or tutorial copy. The initial screen contains a date
range, project filter, charts and saved queries. Use accessible
controls and readable tables; support narrow screens without clipped controls.

## Behavior

1. `/admin` requires a verified Cozy Commons account with a separately assigned
   Commons admin permission. Signing in alone does not grant access. Anonymous
   visitors see a sign-in control; other accounts see `Access denied`. Every
   admin API independently enforces this permission.
2. The default dashboard shows the last 30 UTC calendar days, including today,
   with all projects selected. Show `UTC` beside the date controls and make the
   range inclusive in the UI. Queries use an inclusive start and exclusive end.
   Today is partial. Admins can select a project and a range up to 366 days.
3. Initial projects are Commons home, Dice, Trips, Crowdset, and Fantasy. Keep a project
   registry so adding another client does not require another analytics pipeline.
   Admin and design-preview routes do not count as product traffic.
4. **Active users** means distinct verified signed-in account IDs with at least
   one accepted pageview, search, activity, or product action in that project and range.
   The trend shows daily active users; the summary shows distinct users over the
   whole range, not the sum of daily counts. It does not mean concurrent users,
   registered accounts, or unique anonymous people.
5. A **visit** is a browser session with a rolling 30-minute inactivity expiry.
   Tabs on the same origin share its identifier. A session that touches several
   projects counts once in each project. Repeat route views do not create visits.
   Count distinct session IDs with activity inside the selected range; a session
   spanning midnight can appear on both days. The range total deduplicates it.
6. **Logged-in visits** have at least one event associated with a verified
   signed-in account. **Logged-out visits** have at least one anonymous event.
   These are two distinct counts: a person who signs in during a visit can appear
   in both. Show total distinct visits separately; do not add the two counts to
   produce that total. Put this definition in the metric details, not a banner.
7. Auth transitions generate activity when a project is visible, allowing a
   signed-in user to count without another navigation. Periodic activity reports
   occur only while the document is visible; background tabs do not keep a visit
   alive. Returning after inactivity starts a new visit.
8. Tracking runs on route entry, client-side navigation, and relevant auth
   transitions for every initial project. React development remounts, retries,
   and overlapping hooks do not record the same event twice. Track only pathnames,
   without URL queries or fragments. Browser back/forward is a new pageview.
9. All clients use one generic event contract with a project, event type, event
   name, session ID, unique event ID, and bounded JSON metadata. Authentication
   and timestamps used for metrics come from the server. Browser code cannot
   supply a trusted user ID or login status. Product code can add named action
   events later without building another collector or charting system.
10. Event delivery is best effort and must not block product navigation or
    actions. No durable client queue, ETL, warehouse, scheduled rollup, or offline
    job is introduced. Charts query current source data when opened or refreshed.
    Tracking failures can undercount; anonymous visits are browser sessions, not
    a claim about unique people. Client events are not an audit or billing record.
11. Customization surface: admins can create, edit, run, save,
    duplicate, and delete named SQL queries and choose table, line, or bar views.
    Saved queries are shared by Commons admins and persist across browsers and
    deployments. A visual drag-and-drop query builder is outside the first version.
12. The SQL editor offers the available tables/views and column names. Queries
    can reference the selected date range and project through documented bound
    parameters. Query text never interpolates filter values. The initial metrics
    ship as saved queries using the same runner and renderer as custom charts.
13. A chart saves its query, title, display type, X column, numeric Y columns,
    optional series column, and dashboard placement. Invalid column selections
    show a concise error and preserve the editor contents. Table results remain
    available for inspecting a chart. Empty results show `No data`; errors never
    masquerade as zero. Zero-activity days appear as zero in the initial trends.
14. SQL access is read-only. Attempts to mutate data, issue multiple statements,
    access unapproved data, or execute unsupported functions fail. Slow queries
    time out. Oversized results are capped and explicitly marked as truncated.
    A failed execution does not overwrite saved configuration. Previous draft
    results are cleared when SQL or filters change. Running a query does not save it.
15. Query configuration writes are permitted; product/user data editing is not
    part of this version. Reading user/product data is supported through approved
    queryable projections, beginning with events and a minimal user directory.
    Authentication secrets, credentials, and raw session tokens are never exposed.
16. Loading, forbidden, expired-auth, unavailable-database, query-error, and empty
    states are distinct. Refresh retries failed requests. Cancel or filter changes
    prevent an older response from replacing newer results. Admin responses are
    private and are not cached by shared intermediaries.
17. Historical events remain intact. Legacy rows without verified identity or
    the new session semantics are not silently included in the new metrics.
    Show the earliest accepted version-1 event timestamp; do not invent history or backfill visits
    from server request logs. Legacy event data remains explicitly queryable.

## Chosen scope

- Saved SQL queries and table/line/bar charts, confirmed by Jason.
- Active users and visit definitions above, including overlapping auth segments.
- Build the lightweight workspace inside the existing React/FastAPI applications;
  Broader BI functionality can be reconsidered later.

## Deferred

Offline processing, alternate storage, funnels/cohorts, visual query builder,
scheduled reports, public chart sharing, and user-management mutations.
