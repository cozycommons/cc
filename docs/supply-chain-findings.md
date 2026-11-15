# Supply-chain findings

## November 15 security fixes (PR #270)

CI's live advisory scan found two newly published advisories in existing Python
locks. This change fixes their versions; it adds no advisory ignore and does not
claim that either vulnerable parser is necessarily reachable in every service.

| Package | Advisory and impact | Fixed release | Updated locks |
| --- | --- | --- | --- |
| `opentelemetry-api` | [GHSA-mf5v-w3w3-f6cg](https://osv.dev/vulnerability/GHSA-mf5v-w3w3-f6cg): quadratic traceparent parsing can cause CPU denial of service when untrusted carriers preserve the crafted value, including relevant MCP JSON metadata integrations | `1.45.2` | `backend/requirements.txt`, `backend/app_runtime/requirements.txt`, `backend/requirements-compute.txt`, `backend/requirements-crowdset.txt` |
| `dnspython` | [GHSA-vvf4-9x63-8xvv](https://osv.dev/vulnerability/GHSA-vvf4-9x63-8xvv): attacker-controlled WKS zone-file service numbers can cause excessive memory and CPU use | `2.9.2` | `backend/requirements.txt` |

PyPI's exact-release metadata was checked on 2026-11-15:

- [`opentelemetry-api/1.45.2`](https://pypi.org/pypi/opentelemetry-api/1.45.2/json):
  wheel uploaded `2026-10-29T17:29:06.955093Z`; source archive uploaded
  `2026-10-29T17:29:37.888137Z`.
- [`dnspython/2.9.2`](https://pypi.org/pypi/dnspython/2.9.2/json): wheel uploaded
  `2026-11-03T23:56:52.088419Z`; source archive uploaded
  `2026-11-03T23:56:53.601170Z`.

Both releases already satisfy the seven-day cooldown at the November 15 commit.
The historical global resolver cutoff remains `2026-10-28T00:00:00Z`: advancing
it to November 4 also upgraded unrelated authentication and runtime dependencies.
To keep this repair narrow, exact transitive pins in the affected `.in` files
use the existing package-specific exception mechanism. Their cutoffs are the
first whole second after the final release artifact (`2026-10-29T17:29:38Z` and
`2026-11-03T23:56:54Z`). These overrides allow fixed versions beyond the
historical resolver cutoff; they do **not** admit a release younger than seven
days. Every other package retains its previous version, hashes and global cutoff.

The entries expire on 2026-11-22. Remove these historical-cutoff overrides during
the next reviewed global cutoff refresh by that date; retain suitable security
minimums when changing the exact pins. Hash locks were generated with the
repository-pinned `uv 0.13.7`; all replacement hashes match PyPI metadata.

Independent exception and dependency review: `/root/research_review` explicitly
approved both exact entries on 2026-11-15 after separately checking OSV advisories,
PyPI timestamps and hashes, unyanked status, the seven-day age, expiry and the
package-only lock diff. No advisory ignore or cooldown bypass was approved.
Validation: OSV-Scanner v2.7.0, verified against the CI-pinned binary hash,
reports zero vulnerabilities across all 11 tracked lockfiles. All four affected
Python locks regenerate byte-identically with `uv 0.13.7`. The nine dependency-age
policy tests (including a real resolver boundary check), two OSV policy tests,
and the complete npm cooldown check (415 versions across two locks) pass. Application tests against the patched install are tracked in PR #270.

---

## Historical advisory baseline, 2026-11-05

After integrating main through `da0c305`, OSV-Scanner v2.7.0 reports only the
packages covered by pending remediation PRs #230 and #231. No advisories are
ignored or accepted. Re-run after those PRs merge; the expected result is zero.

## Pending #230

### pillow 12.3.0

Lock: `backend/requirements.txt`.

Advisories: GHSA-22hg-r758-rrw9, GHSA-24rc-8hj2-v98c, GHSA-254f-3936-288h, GHSA-27h8-gf7j-v5hc, GHSA-332p-7hrc-92wf, GHSA-3j72-p6qg-6xp7, GHSA-4558-3h8r-v8xp, GHSA-462x-pgg6-55fp, GHSA-4rm8-3hmm-39fg, GHSA-4rr5-89j8-mwwm, GHSA-58r4-6rv3-gfh8, GHSA-5x8w-8jj5-q52h, GHSA-5xm2-6676-qcp9, GHSA-654x-cwwv-5j9c, GHSA-65qm-jvmh-6pqg, GHSA-74r2-7ff9-mjj2, GHSA-78g4-xqwv-q3g8, GHSA-7mwm-ghpf-9vrm, GHSA-8g5g-8vmr-9782, GHSA-9v9v-9qvf-h2hj, GHSA-c6hw-5grf-ff96, GHSA-cp9v-662q-vvx9, GHSA-f2g6-542v-9j58, GHSA-fc9g-5qg7-mf45, GHSA-g4qv-2jxx-769h, GHSA-g7cr-3p24-7wf7, GHSA-g842-9rc4-69pw, GHSA-gg2r-wvfm-q9rx, GHSA-j4m9-6w36-pw47, GHSA-jg86-v3jv-hrpm, GHSA-mrfp-p49p-3hf2, GHSA-p4wg-p73j-c528, GHSA-p8hx-v2p6-rp84, GHSA-pchr-8j38-3x4p, GHSA-q45j-58j2-45rg, GHSA-rfgq-q3w2-pmv2, GHSA-v9pv-5gc8-w2m6, GHSA-vx6w-vv9f-6gvg, GHSA-w889-685w-c8fh, GHSA-xgh8-jp6q-p5x8, GHSA-xvh5-g6gv-559v, PYSEC-2026-4326, PYSEC-2026-4327, PYSEC-2026-4328, PYSEC-2026-4329, PYSEC-2026-4330, PYSEC-2026-4331, PYSEC-2026-4332, PYSEC-2026-4333, PYSEC-2026-4334, PYSEC-2026-4335, PYSEC-2026-4336, PYSEC-2026-4337, PYSEC-2026-4338, PYSEC-2026-4339, PYSEC-2026-4340, PYSEC-2026-4341, PYSEC-2026-4342, PYSEC-2026-4343.

## Pending #231

### @babel/core 7.28.0

Lock: `frontend/package-lock.json`.

Advisories: GHSA-4x5r-pxfx-6jf8.

### @remix-run/router 1.23.0

Lock: `frontend/package-lock.json`.

Advisories: GHSA-2j2x-hqr9-3h42, GHSA-2w69-qvjg-hvjx.

### @vitest/mocker 4.0.17

Lock: `frontend/package-lock.json`.

Advisories: GHSA-82fw-gwwq-j7x9, GHSA-qxg6-89mg-rqv8.

### browserslist 4.25.2

Lock: `frontend/package-lock.json`.

Advisories: GHSA-73wf-gq98-2v4g, GHSA-c83g-rgw3-j3cx.

### esbuild 0.21.5

Lock: `frontend/package-lock.json`.

Advisories: GHSA-67mh-4wv8-2f99.

### nanoid 3.3.11

Lock: `frontend/package-lock.json`.

Advisories: GHSA-28wg-ghj8-5hjv, GHSA-2v37-7h3g-55p8, GHSA-xwg4-73v4-xw9w.

### picomatch 4.0.3

Lock: `frontend/package-lock.json`.

Advisories: GHSA-3v7f-55p6-f55p, GHSA-c2c7-rcm5-vvqj.

### postcss 8.5.6

Lock: `frontend/package-lock.json`.

Advisories: GHSA-6g55-p6wh-862q, GHSA-fxqj-rqcc-2cmp, GHSA-qx2v-qp2m-jg93, GHSA-r28c-9q8g-f849.

### react-router 6.30.1

Lock: `frontend/package-lock.json`.

Advisories: GHSA-2j2x-hqr9-3h42, GHSA-337j-9hxr-rhxg, GHSA-9jcx-v3wj-wh4m, GHSA-wrjc-x8rr-h8h6.

### rollup 4.55.3

Lock: `frontend/package-lock.json`.

Advisories: GHSA-mw96-cpmx-2vgc.

### source-map-js 1.2.1

Lock: `frontend/package-lock.json`.

Advisories: GHSA-68fv-2mgg-jv7q.

### tar 7.4.3

Lock: `frontend/package-lock.json`.

Advisories: GHSA-23hp-3jrh-7fpw, GHSA-34x7-hfp2-rc4v, GHSA-83g3-92jg-28cx, GHSA-8qq5-rm4j-mr97, GHSA-8x88-c5mf-7j5w, GHSA-9ppj-qmqm-q256, GHSA-gvwx-54wh-qm9j, GHSA-qffp-2rhf-9h96, GHSA-r292-9mhp-454m, GHSA-r6q2-hw4h-h46w, GHSA-vmf3-w455-68vh, GHSA-w8wr-v893-vjvp.

### vite 5.4.19

Lock: `frontend/package-lock.json`.

Advisories: GHSA-4w7w-66w2-5vf9, GHSA-587h-7wmj-h5pm, GHSA-698v-4r3x-3vcv, GHSA-93m4-6634-74q7, GHSA-9jrq-w75r-8gcw, GHSA-fx2h-pf6j-xcff, GHSA-g4jq-h2w9-997c, GHSA-jqfw-vq24-v9c3, GHSA-r825-w8mm-5pxw, GHSA-rq7h-c2jc-7f22, GHSA-v6wh-96g9-6wx3.

### vite 7.3.1

Lock: `frontend/package-lock.json`.

Advisories: GHSA-4w7w-66w2-5vf9, GHSA-587h-7wmj-h5pm, GHSA-698v-4r3x-3vcv, GHSA-9jrq-w75r-8gcw, GHSA-fx2h-pf6j-xcff, GHSA-p9ff-h696-f583, GHSA-r825-w8mm-5pxw, GHSA-rq7h-c2jc-7f22, GHSA-v2wj-q39q-566r, GHSA-v6wh-96g9-6wx3.

### vitest 4.0.17

Lock: `frontend/package-lock.json`.

Advisories: GHSA-5xrq-8626-4rwp, GHSA-82fw-gwwq-j7x9.

### ws 8.19.0

Lock: `frontend/package-lock.json`.

Advisories: GHSA-58qx-3vcg-4xpx, GHSA-96hv-2xvq-fx4p.

