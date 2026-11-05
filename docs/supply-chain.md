# Supply-chain checks

The always-on CI `changes` job checks dependency age, scans all five Python
hash locks and both npm locks with OSV-Scanner, and audits workflows with zizmor.
The existing five-minute job timeout stays in place. Scanner steps have two-minute
limits; OSV's Linux binary is SHA-256 verified and zizmor's action is commit-SHA
pinned with a fixed, hash-locked tool version. No additional secrets are used.

## Seven-day release cooldown

`scripts/lock-backend-requirements.sh` rejects missing, malformed, relative, or
naive `uv-exclude-newer` timestamps. A cutoff must be at least seven 24-hour days
before the checked-out commit's committer timestamp (`git log -1 --format=%ct`).
Bump the fixed UTC cutoff in the appropriate `.in` file, regenerate its `.txt`,
and commit both. Before committing, HEAD is the reference date; after committing,
rerun the command to verify against the final commit. CI uses the checkout commit,
including GitHub's merge commit on pull requests. Commit timestamps are trusted
repository metadata, not an independent trusted clock.

`python3 scripts/check-dependency-age.py` checks every registry package version
in every tracked npm lock against npm's registry `time` metadata, including dev
and optional dependencies. Missing metadata and non-registry sources fail closed.
Requests are deduplicated by name and run with twelve workers and a 20-second
request timeout. Successful responses are cached locally in
`.cache/dependency-age/<commit>/`; CI starts cold. No cache action or cross-PR
cache is trusted. The npm check does not install or execute dependencies.

## Urgent security exceptions

Normally wait seven days. For an urgent security fix, add an entry to
`dependency-age-exceptions.json` in the same PR as the dependency change, with
`ecosystem`, `name`, `version`, `reason`, `reviewed_by`, `reviewed_on`, and
`expires`. Dates use `YYYY-MM-DD`; expiry is mandatory and at most 30 days after
review. Name the advisory, explain why waiting is worse, and link the independent
security review in the reason. A named reviewer must actually approve the exact
exception before merge; metadata validation cannot prove human approval.

For npm, use ecosystem `npm`, the registry package name, and exact version.
For Python, use ecosystem `pypi-lock`, the repo-relative `.in` path as `name`,
and its exact UTC cutoff as `version`. This exception permits the whole lock's
newer cutoff, so the reviewer must review **every changed transitive version**
in that regenerated lock, not only the urgent direct dependency. Keep the
cutoff as early as possible. Remove exceptions after the releases age out.
No exceptions are currently accepted.

## Advisory exceptions

Run `OSV_SCANNER=/path/to/osv-scanner scripts/scan-dependencies.sh` with
OSV-Scanner v2.7.0. All known advisories fail CI. Accepted advisories go in
`osv-scanner.toml` using `[[IgnoredVulns]]`, an exact `id`, `ignoreUntil` date,
and a `reason` naming the reviewer, review date, advisory, affected paths,
reachability evidence, and remediation plan. Keep expiry within 30 days of review.
OSV expires ignores automatically. Do not add broad package overrides.
Changes to ignores require independent security review before merge.

## Existing GitHub coverage

On 2026-11-05 the repository API reported CodeQL default setup configured with
`query_suite: extended`, `threat_model: remote`, and standard runners. Although its
setup `languages` response was empty, the analyses API showed completed Python,
JavaScript/TypeScript, and Actions scans at 03:00 UTC on November 5, with no
reported errors or warnings. This PR adds no CodeQL workflow. CodeQL Actions
analysis overlaps workflow security analysis; zizmor adds the explicitly requested
medium-or-higher local/CI gate, including checkout credential persistence.
Neither replaces lockfile advisory matching or release-age policy.

The repository API also reported secret scanning and push protection enabled.
Non-provider secret patterns and validity checks were disabled. These features
cover supported credential patterns in repository content and pushes; no second
secret scanner or new credentials are introduced here.
