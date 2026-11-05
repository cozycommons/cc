# Advisory baseline, 2026-11-05

OSV-Scanner v2.7.0 reports the following findings after restoring npm artifact
metadata and enforcing the Python cutoff in the actual uv invocation. None are
ignored or accepted. Executor R owns remediation; its stack merges before this
PR is updated onto main. Re-run scanners after integrating that stack and retain
the npm artifact binding fields when resolving lockfile conflicts.

## @babel/core 7.28.0

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 7.29.6, 8.0.0-rc.6. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-4x5r-pxfx-6jf8.

## @remix-run/router 1.23.0

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 1.23.2, 1.23.3, 6.30.4, 7.12.0, 7.14.1. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-2j2x-hqr9-3h42, GHSA-2w69-qvjg-hvjx.

## @vitest/mocker 4.0.17

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 4.1.11, 4.1.12, 5.0.0-rc.2, 5.0.3. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-82fw-gwwq-j7x9, GHSA-qxg6-89mg-rqv8.

## brace-expansion 5.0.7

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 1.1.17, 1.1.18, 1.1.19, 1.1.20, 1.1.21, 2.1.3, 2.1.4, 2.1.5, 2.1.6, 2.1.7, 3.0.3, 3.0.6, 3.0.7, 3.0.8, 3.0.9, 5.0.10, 5.0.11, 5.0.12, 5.0.8, 5.0.9. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-6j4f-fj2g-mc7p, GHSA-mh99-v99m-4gvg, GHSA-q2hr-2g5m-vwhr, GHSA-qhr7-859c-m2p7, GHSA-rgw5-rvv9-x895.

## browserslist 4.25.2

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 4.28.7. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-73wf-gq98-2v4g, GHSA-c83g-rgw3-j3cx.

## diskcache 5.6.3

Paths: `backend/requirements.txt`.

OSV fixed-version boundaries: none published. No published fix. Assess the FastMCP cache path or remove the dependency as part of the FastMCP migration.

Advisories: GHSA-w8v5-vhqr-4h9v, PYSEC-2026-2447.

## esbuild 0.21.5

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 0.25.0. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-67mh-4wv8-2f99.

## fastmcp 2.14.7

Paths: `backend/requirements.txt`.

OSV fixed-version boundaries: 3.2.0. Requires a 2.x to 3.x migration; verify tool registration and authentication contracts.

Advisories: GHSA-m8x7-r2rg-vh5g, GHSA-rww4-4w9c-7733, GHSA-vv7q-7jx5-f767, PYSEC-2026-2475, PYSEC-2026-2476, PYSEC-2026-338.

## minimatch 10.2.5

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 11.0.1. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-g3hv-75wg-m249.

## nanoid 3.3.11

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 3.3.12, 3.3.16, 3.3.18, 5.1.11, 5.1.16, 5.1.6. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-28wg-ghj8-5hjv, GHSA-2v37-7h3g-55p8, GHSA-xwg4-73v4-xw9w.

## picomatch 4.0.3

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 2.3.2, 3.0.2, 4.0.4. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-3v7f-55p6-f55p, GHSA-c2c7-rcm5-vvqj.

## pillow 12.3.0

Paths: `backend/requirements.txt`.

OSV fixed-version boundaries: 13.0.0. Requires a 12.x to 13.x migration; verify image decoding consumers.

Advisories: GHSA-22hg-r758-rrw9, GHSA-24rc-8hj2-v98c, GHSA-254f-3936-288h, GHSA-27h8-gf7j-v5hc, GHSA-332p-7hrc-92wf, GHSA-3j72-p6qg-6xp7, GHSA-4558-3h8r-v8xp, GHSA-462x-pgg6-55fp, GHSA-4rm8-3hmm-39fg, GHSA-4rr5-89j8-mwwm, GHSA-58r4-6rv3-gfh8, GHSA-5x8w-8jj5-q52h, GHSA-5xm2-6676-qcp9, GHSA-654x-cwwv-5j9c, GHSA-65qm-jvmh-6pqg, GHSA-74r2-7ff9-mjj2, GHSA-78g4-xqwv-q3g8, GHSA-7mwm-ghpf-9vrm, GHSA-8g5g-8vmr-9782, GHSA-9v9v-9qvf-h2hj, GHSA-c6hw-5grf-ff96, GHSA-cp9v-662q-vvx9, GHSA-f2g6-542v-9j58, GHSA-fc9g-5qg7-mf45, GHSA-g4qv-2jxx-769h, GHSA-g7cr-3p24-7wf7, GHSA-g842-9rc4-69pw, GHSA-gg2r-wvfm-q9rx, GHSA-j4m9-6w36-pw47, GHSA-jg86-v3jv-hrpm, GHSA-mrfp-p49p-3hf2, GHSA-p4wg-p73j-c528, GHSA-p8hx-v2p6-rp84, GHSA-pchr-8j38-3x4p, GHSA-q45j-58j2-45rg, GHSA-rfgq-q3w2-pmv2, GHSA-v9pv-5gc8-w2m6, GHSA-vx6w-vv9f-6gvg, GHSA-w889-685w-c8fh, GHSA-xgh8-jp6q-p5x8, GHSA-xvh5-g6gv-559v, PYSEC-2026-4326, PYSEC-2026-4327, PYSEC-2026-4328, PYSEC-2026-4329, PYSEC-2026-4330, PYSEC-2026-4331, PYSEC-2026-4332, PYSEC-2026-4333, PYSEC-2026-4334, PYSEC-2026-4335, PYSEC-2026-4336, PYSEC-2026-4337, PYSEC-2026-4338, PYSEC-2026-4339, PYSEC-2026-4340, PYSEC-2026-4341, PYSEC-2026-4342, PYSEC-2026-4343.

## postcss 8.5.6

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 8.5.10, 8.5.12, 8.5.18, 8.5.23. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-6g55-p6wh-862q, GHSA-fxqj-rqcc-2cmp, GHSA-qx2v-qp2m-jg93, GHSA-r28c-9q8g-f849.

## pyjwt 2.10.1

Paths: `backend/requirements.txt`.

OSV fixed-version boundaries: 2.12.0, 2.12.1, 2.13.0, 2.14.0, 2.15.0. Upgrade and verify JWT validation and Supabase integration behavior.

Advisories: GHSA-2gx3-rcp4-g85q, GHSA-42vr-xj54-vc7v, GHSA-752w-5fwx-jx9f, GHSA-993g-76c3-p5m4, GHSA-9v7f-9g4p-ffgj, GHSA-ffc3-869f-jxw9, GHSA-fhv5-28vv-h8m8, GHSA-hxm8-2xgr-2p9m, GHSA-jq35-7prp-9v3f, GHSA-jwrc-g2q2-pq5p, GHSA-p4g4-x82p-q773, GHSA-pxh4-856f-4h89, GHSA-w6j9-cwv2-h6wq, GHSA-w7vc-732c-9m39, GHSA-x33g-cr3x-6449, GHSA-xgmm-8j9v-c9wx, PYSEC-2025-183, PYSEC-2026-120, PYSEC-2026-175, PYSEC-2026-176, PYSEC-2026-177, PYSEC-2026-178, PYSEC-2026-179, PYSEC-2026-4140, PYSEC-2026-4141, PYSEC-2026-4144, PYSEC-2026-4145, PYSEC-2026-4147, PYSEC-2026-4148, PYSEC-2026-4149, PYSEC-2026-4152, PYSEC-2026-4183.

## pytest 8.3.4

Paths: `backend/compute/tests/requirements.txt`, `backend/crowdset/tests/requirements.txt`, `backend/requirements.txt`.

OSV fixed-version boundaries: 9.0.3. Upgrade the shared and standalone test environments together; verify plugin compatibility.

Advisories: GHSA-6w46-j5rx-g56g, PYSEC-2026-1845.

## python-dotenv 1.1.0

Paths: `backend/requirements.txt`.

OSV fixed-version boundaries: 1.2.2. Upgrade and verify sandbox environment-loading guards.

Advisories: GHSA-mf9w-mj56-hr94, PYSEC-2026-2270.

## react-router 6.30.1

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 1.23.3, 6.30.2, 6.30.4, 7.14.1, 7.18.0, 7.9.6. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-2j2x-hqr9-3h42, GHSA-337j-9hxr-rhxg, GHSA-9jcx-v3wj-wh4m, GHSA-wrjc-x8rr-h8h6.

## rollup 4.55.3

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 2.80.0, 3.30.0, 4.59.0. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-mw96-cpmx-2vgc.

## source-map-js 1.2.1

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 1.2.2. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-68fv-2mgg-jv7q.

## starlette 0.41.3

Paths: `backend/requirements-compute.txt`, `backend/requirements-crowdset.txt`, `backend/requirements.txt`.

OSV fixed-version boundaries: 0.47.2, 0.49.1, 1.0.1, 1.1.0, 1.3.0, 1.3.1. FastAPI 0.115.6 constrains Starlette to an affected series. Upgrade FastAPI with Starlette and verify shared API behavior.

Advisories: GHSA-2c2j-9gv5-cj73, GHSA-7f5h-v6xp-fcq8, GHSA-82w8-qh3p-5jfq, GHSA-86qp-5c8j-p5mr, GHSA-jp82-jpqv-5vv3, GHSA-wqp7-x3pw-xc5r, GHSA-x746-7m8f-x49c, PYSEC-2026-161, PYSEC-2026-1941, PYSEC-2026-1942, PYSEC-2026-2280, PYSEC-2026-2281, PYSEC-2026-248, PYSEC-2026-249.

## tar 7.4.3

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 7.5.10, 7.5.11, 7.5.16, 7.5.17, 7.5.18, 7.5.19, 7.5.21, 7.5.3, 7.5.4, 7.5.7, 7.5.8. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-23hp-3jrh-7fpw, GHSA-34x7-hfp2-rc4v, GHSA-83g3-92jg-28cx, GHSA-8qq5-rm4j-mr97, GHSA-8x88-c5mf-7j5w, GHSA-9ppj-qmqm-q256, GHSA-gvwx-54wh-qm9j, GHSA-qffp-2rhf-9h96, GHSA-r292-9mhp-454m, GHSA-r6q2-hw4h-h46w, GHSA-vmf3-w455-68vh, GHSA-w8wr-v893-vjvp.

## vite 5.4.19

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 0.1.24, 1.1.0, 2.14.1, 2.14.2, 5.4.20, 5.4.21, 6.3.6, 6.4.1, 6.4.2, 6.4.3, 6.4.4, 7.0.7, 7.0.8, 7.1.11, 7.1.5, 7.3.2, 7.3.5, 7.3.7, 8.0.16, 8.0.5, 8.1.6, 8.2.4, 8.3.3. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-4w7w-66w2-5vf9, GHSA-587h-7wmj-h5pm, GHSA-698v-4r3x-3vcv, GHSA-93m4-6634-74q7, GHSA-9jrq-w75r-8gcw, GHSA-fx2h-pf6j-xcff, GHSA-g4jq-h2w9-997c, GHSA-jqfw-vq24-v9c3, GHSA-r825-w8mm-5pxw, GHSA-rq7h-c2jc-7f22, GHSA-v6wh-96g9-6wx3.

## vite 7.3.1

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 0.1.24, 1.1.0, 2.14.1, 2.14.2, 6.4.2, 6.4.3, 6.4.4, 7.3.2, 7.3.5, 7.3.7, 8.0.16, 8.0.5, 8.1.6, 8.2.4, 8.3.3. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-4w7w-66w2-5vf9, GHSA-587h-7wmj-h5pm, GHSA-698v-4r3x-3vcv, GHSA-9jrq-w75r-8gcw, GHSA-fx2h-pf6j-xcff, GHSA-p9ff-h696-f583, GHSA-r825-w8mm-5pxw, GHSA-rq7h-c2jc-7f22, GHSA-v2wj-q39q-566r, GHSA-v6wh-96g9-6wx3.

## vitest 4.0.17

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 3.2.6, 4.1.0, 4.1.11, 5.0.0-rc.2. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-5xrq-8626-4rwp, GHSA-82fw-gwwq-j7x9.

## ws 8.19.0

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 5.2.5, 6.2.4, 7.5.11, 8.20.1, 8.21.0. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-58qx-3vcg-4xpx, GHSA-96hv-2xvq-fx4p.

## zod 4.5.4

Paths: `frontend/package-lock.json`.

OSV fixed-version boundaries: 4.6.6. Update the npm dependency tree in executor R's remediation stack and verify frontend tests, lint and builds.

Advisories: GHSA-mrhx-c7xc-m3w5.

