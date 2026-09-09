# Execution plan for small implementation agents

Status: implementation in progress on `commons-ambient-scene`. W02, W09, W10 and W11 have working slices; W12 and W13 are partially integrated. W01, W03–W08 and W14 still require their stated visual/art or release evidence. Keep this tracker honest as commits land.

## Selected direction and delivery order

Read [DIRECTION](DIRECTION.md) first. Workers serialize and implement those decisions; engine choice, world projection, art pipeline, build-time character assembly and state authority are already selected. The integrating lead owns cross-task decisions and G0/G1/G2 acceptance.

Build one convincing slice before multiplying assets. The dependency chain is:

```
W01 baseline → W02 spatial/catalog contract → W03 art slice + W04 renderer slice
W03 + W04 → G1 grounded/occluding slice
G1 → W05 character kit → W06 character runtime
G1 → W07 environment pack → W08 room layout
W02 → W09 backend timeline → W10 client timeline
W08 + W09 → W11 state migration
W04 + W06 + W07 + W10 + W11 → W12 integration
W12 → W13 passive homepage → W14 visual/performance acceptance
```

Parallel work is safe only after input contracts are committed/frozen in the implementation branch. W03 and W04 share fixture IDs and frame registration from W02; W04 can use deliberately simple placeholder shapes until W03 delivers art. W05 and W07 can run independently once the common art template passes G1. W09 need not wait for final art, but its validator consumes the same semantic catalog. Integration begins after all interface fixtures pass.

Do not let one worker change the shared contract while other workers implement the old version. Contract changes go through the integrating agent and update documentation, fixtures, generated artifacts and consumers together. A worker owns only its declared files; if the repository evolves, inspect actual paths before editing. Suggested new paths below are design choices, not claims that those files already exist.

## Universal worker packet

Give each worker the following introduction plus its task below:

> Implement only Wxx from docs/commons-ambient-scene/PLAN.md. Read DIRECTION, README, the cited PRODUCT/TECH sections, repository AGENTS.md, and the task's input artifacts. Inspect current git status and preserve unrelated work. Do not alter Dice, historical migrations, credentials, production, or sandbox guards. Work only in your owned paths; request coordination from the integrating agent for shared-file changes. Run the task's checks. Return changed paths, interface/schema changes, exact checks and outcomes, visual evidence where required, and remaining risks. Do not report completion from mock/unit tests when the task requires rendered proof. If the task grows beyond one coherent change, split it into explicit follow-up packets rather than silently reducing acceptance.

Every handoff includes: baseline commit; output commit/diff; a concise implementation summary; fixture inputs and how to reproduce them; exact artifact locations; test results; unsupported cases; and any contract change. Never leave an unregistered asset, unexplained magic offset, or a known depth error for “polish later.”

## W01 — Capture and establish the baseline

**Scope:** Read current renderer/API and visually inspect the running local homepage at 1440×900 and 390×844. Capture a paused/initial image and 30 seconds including existing walking, rug crossing and lamp/music effects. Inspect supplied art sources at native scale. Record source commit, viewport, DPR and state source. Use only the repository's local sandbox workflow; no production database or old deployment.

**Owned outputs:** `art/commons/review/baseline/` evidence and a compact baseline note. No production implementation changes.

**Checks:** Distinguish running screenshots from source assets/concepts. Record existing warm/cold lighting, mismatched projection, support gaps, current route speed and UI clutter. The follow-up planning review inspected live desktop/mobile screenshots and the grid overlay after the Mac was unlocked (see AUDIT). This task still produces saved, repeatable recordings, controlled traversal and DPR 1/2 evidence before implementation choices are visually accepted.

**Done:** A reviewer can reproduce the current scene and compare subsequent captures under the same conditions. If a browser remains unavailable, backend/pure contract work can proceed, but G1 visual approval stays pending.

## W02 — Freeze geometry, manifest and fixture contracts

**Inputs:** TECH §§2–5 and current `commons-grid.js`, backend geometry/defaults, and migrations.

**Owned outputs:** `shared/commons/scene-contract-v1.json`, new `world/geometry.js`, contract documentation/fixtures. Coordinate edits to existing grid import sites with integration; do not change their behavior independently.

**Work:** Define strict discrete bounds and continuous projection; encode the selected source scale/rig registration; name stable asset IDs; represent per-orientation coverage/blocking cells and support metadata. Create fixture snapshots for rug, three-cell sofa, tall plant, one actor and a diagnostic continuous path around each. Provide expected projection points, unsupported-orientation rejection and catalog hash behavior.

**Checks:** Integer/fractional projection inverse, invalid coordinate rejection, frontend/backend fixture parity, at least one trimmed-frame registration example and layout bounds. No global clamp in authoritative validation. Include deployment packaging requirements for shared JSON.

**Done / G0:** Subsequent workers can implement independently from actual machine-readable examples. Any schema refinement updates TECH now, before asset duplication.

## W03 — Art vertical slice

**Inputs:** W02 template; PRODUCT art direction and G1–G5.

**Owned outputs:** Editable art sources and exports for one sofa and one table with depth pieces, one woven rug, one tall plant, one lamp, the complete projected floor/shell outline, one resident's four planted views and eight-frame walks in all four views, with blink/breath/glance layers; their manifest fragment and contact sheet. Store under `art/commons/v2/slice/` and staged public pack paths agreed with integration.

**Work:** Use the selected layered 2D source pipeline and match the 96×60 source tile; author contact anchors/supports, clean transparency, shared shadow direction and occlusion pieces. Place the sample resident beside sofa/chair-height guides. Export a static full-size and actual-display-size contact sheet. Use original furnished illustration for warmth and material detail, not a pasted background or an unmeasured projection.

**Checks:** No baked fringe/shadow interfering with pivots; complete disjoint depth masks; sofa footprint/support fit; all planted views retain identical root; no arbitrary per-entity scaling.

**Done:** Art works at native resolution and desktop/mobile display scale. No final room-wide pack until G1 passes. For small workers, dispatch this packet as four serial deliverables: calibrated shell/props, registered resident idle views, four walk strips, then the combined proof sheet. The same owner retains registration responsibility.

## W04 — Renderer spatial slice

**Inputs:** W02 and W03 (temporary registered geometric assets allowed while waiting).

**Owned outputs:** `render/asset-registry.js`, `grounding.js`, `depth.js`; development-only fixtures and direct tests. Small adapter changes are coordinated with integrating agent.

**Work:** Load manifests, register trimmed/untrimmed frames, render pass separation, rug floor pass, contact shadows, continuous stable depth, multi-piece furniture. Add development overlay and injected time/path scrubber. Include a minimal fixture-only frame/pose driver for the complete W03 resident so G1 can prove four-direction gait and idle registration before W06 builds the reusable runtime. This driver must not become a second production animation system. Keep inspector input isolated from public runtime input.

**Checks:** V01–V04 below in actual Phaser; shuffle entity map insertion order; capture every sofa side/corner and rug edge. No frame position patch keyed by actor ID. Verify floor/shell projection at all corners: the room floor boundary and grid domain must coincide, not merely share edge angles. Include the current rug/console approach where the maker’s lower legs disappear behind the rug.

**Done / G1:** One visually excellent four-direction actor/sofa/table/rug/plant and full-floor-outline slice passes grounding and all traversal cases. The integrating agent reviews actual images and motion. If slicing fails, revise the prop decomposition and contracts here; do not propagate the failure into a larger pack.

## W05 — Complete reusable character art kit

**Inputs:** Frozen rig after G1, TECH §5.

**Owned outputs:** Character source layers, part atlases, per-view/per-pose layer order, compatibility metadata, appearance samples under `art/commons/v2/characters/` and approved public pack paths.

**Work:** Deliver all eight gait frames in all four views, planted idle/breath layers, a reusable glance pose, and eye masks. Produce the minimum variant inventory from PRODUCT C2/TECH §5 and complete host/maker/neighbor appearances. Keep accessory handedness and clothing lighting consistent across turns. No renderer code or bespoke character-specific conditionals.

**Checks:** Registered overlay sheet, all parts cover all required poses, twelve valid combinations, rear views with no front eyes, asymmetric accessory seen from every side, compatible palette masking.

**Done:** Another agent can create a thirteenth valid resident by choosing parts in a descriptor, without painting a new complete character or modifying runtime logic.

## W06 — Build-time character composition and pose runtime

**Inputs:** W05 and TECH §5.

**Owned outputs:** `scripts/commons-art/` build-time compositor, `characters/recipes.js`, `pose.js`, texture ownership, targeted tests and character gallery fixture.

**Work:** Validate descriptors and deterministically export selected recipes at build time. Runtime resolves those outputs and implements direction mapping, distance-based gait, upper-body breathing, glance and blink phases. Inject motion policy/time. Release owned textures. Missing/invalid recipes fail the build or reject the candidate snapshot; retain the last valid scene or static initial fallback, never a fabricated live resident.

**Checks:** V05, foot-slip measurement, all directions/turns, pause/reduced-motion, repeated creation/disposal, unknown/missing output rejection without mixing rigs. Measure texture memory for the three-resident shipping pack; the twelve-resident gallery uses separate developer outputs. Assert component source atlases/compositor are absent from runtime bundles.

**Done:** Runtime changes appearance entirely through data; every production resident reads as the same coherent art family.

## W07 — Environment art pack

**Inputs:** G1, PRODUCT composition and TECH §§3–4.

**Owned outputs:** Editable shell/floor/prop/light sources, atlases and measured manifest fragments for every seeded asset.

**Work:** Produce empty-floor rear shell plus occluding architectural pieces, tileable floor with subtle variation, rugs, sofa/loveseat, tables/chairs, console, lamp and plants; omitted armchair/stool remain legacy-only assets. Retain only props needed by the final layout. Provide actual south/north variants where existing state can reference both; no synthetic mirrored-back assumptions. Tabletop accessories are baked or explicitly attached. Include a coherent static fallback derived from the final room once layout is available.

**Checks:** All seeded IDs and supported orientations resolved, no duplicate floor geometry, floor seams at tile borders, projection template fit, complete anchors/pieces and provenance. Repeat contact sheet for all assets, not only the slice.

**Done:** No placeholder/prototype art is used by final state. Asset totals meet provisional budgets or include a concrete measured reduction plan before integration.

## W08 — Author exact room layout and ambient score

**Inputs:** W07, shared catalog, PRODUCT zone envelopes and TECH §6.

**Owned outputs:** Exact candidate scene JSON and compiled 180-second ambient program under shared fixtures/authoring data; top-down occupancy map and annotated composition image.

**Work:** Fit each entity to actual support/collision geometry. Compose open circulation, listening/table/window zones and balanced light. Assign three safe home anchors and one-at-a-time walks with long holds. Select semantic object states and appearances. Author every hold/path/duration/facing; do not leave destinations for client random selection.

**Checks:** DIRECTION score windows and ≤20 seconds walking per resident, no simultaneous walks, loop continuity, route clearance, all holds safe, all support points in room, target composition from PRODUCT. Evaluate all occupied time intervals including wrap. Render both a paused full room and full-cycle preview using integration fixtures.

**Done:** Exact state replaces approximate zone envelopes; a fresh seed requires no subsequent manual dragging. Coordinate final layout proof with W12 if renderer integration is still pending.

## W09 — Backend catalog and ambient contract

**Inputs:** W02, TECH §§6–7, backend audit.

**Owned outputs:** New Commons validation/timeline helpers and focused edits to `schemas.py`, `scene_service.py`, `routes.py`, associated tests. Coordinate shared catalog modifications rather than forking defaults.

**Work:** Validate schema/catalog/appearance/program; add response-level server time; retain API envelope/version behavior. Define read-only evaluation semantics and atomic program invalidation for relevant commands. Address the known replay ordering defect while changing command invalidation, preserving identical-payload receipt replay and conflicting-payload rejection. Include unknown/new schema handling and program-disabled home anchors.

**Checks:** Valid/invalid schedule fixtures, wrap/hold collisions, overlap timing rejection, catalog deployment resolution, stale versions, identical command replay and differing-payload conflict, orientation footprint validation, zero writes on GET. Do not test only a mocked happy-path RPC.

**Done:** Backend serves a compact validated snapshot that frontend can evaluate without local path choices. No migration application or production access is bundled into this packet.

## W10 — Client ambient clock and motion policy

**Inputs:** W09 response fixtures and TECH §6.

**Owned outputs:** `ambient/timeline.js`, `motion-policy.js`, unit tests, reconciliation fixture.

**Work:** Pure route interpolation with explicit segment/edge time, seeded idle timing, server-time estimate, offset correction, pause/resume, visibility, 30-second freshness limit, revision changes and error handling. Supply pose to renderer; do not mutate snapshots or issue commands. Ensure repeated polls do not restart animation.

**Checks:** Exact cycle boundary, hold/walk transitions, slow/fast/out-of-order responses, reliable/unreliable time samples, two clients with known offsets, paused live state update, reduced-motion change mid-walk, hidden-tab long return, offline-safe endpoint. Fake time tests must assert expected poses, not only timer calls.

**Done:** Identical snapshot/time inputs yield identical poses; state remains authoritative and the motion budget is enforced centrally.

## W11 — Additive state migration and seed validation

**Inputs:** W08 exact layout/program, W09 validators, TECH §7, repository migration workflows.

**Owned outputs:** Next correctly numbered Commons migration, schema contract version update, upgrade/fresh-seed fixtures, focused validation tooling/documentation. Historical migrations are read-only.

**Work:** Upgrade metadata preserving IDs, booleans and receipts; apply new composition only to exact untouched seed; preserve compatible customized layouts with safe resting residents; retain explicit legacy schema/catalog and static adapter for incompatible custom layouts. Update attestation/semantic tests as specified. Verify backend deployment carries the shared catalog.

**Checks:** `scripts/commons-dev.sh check`; loopback-only `scripts/commons-dev.sh local-migrate`; actual post-migration JSON validation, second-application behavior, custom legacy layout preservation, service-role/RLS checks and rollback adapter rehearsal. Follow required Supabase skill and repository safeguards during implementation.

**Done:** Fresh and existing local states render coherently without destructive resets. Report resulting schema, layout and CAS versions distinctly.

## W12 — Integrate full renderer and state-backed effects

**Inputs:** W04/W06/W07/W10/W11.

**Owned outputs:** `commons-phaser.js` adapter/refactor integration, `render/effects.js`, remaining integration tests. Avoid unrelated React UI changes owned by W13.

**Work:** Replace hardcoded local ambient routes and old asset scaling; wire snapshot, pose, motion policy, owner-bound light/leaf/steam systems. Ensure semantic off state disables appropriate effects. Remove stale loops/listeners. Integrate full room, final static fallback and asset failure handling.

**Checks:** Full-cycle room preview, state updates while idle/walking/paused, missing texture, unknown catalog, WebGL failure fallback, renderer remount, effect depth and total particle budget. No retained hidden local simulation and no per-frame network activity.

**Done:** Runtime scene satisfies contracts using actual backend state, not a fixture secretly shipped as production truth.

## W13 — Passive homepage and accessible controls

**Inputs:** W12 and PRODUCT homepage requirements.

**Owned outputs:** `CommonsHome.jsx`, `CommonsScene.jsx`, scene/theme CSS and related React tests.

**Work:** Simplify overlays, semantic description, pause control, fixed aspect loading/fallback, connection status and mobile layout. Remove default global movement/drag/context-menu/touch suppression and mutation replay. Keep development inspector opt-in. Preserve queued commands for explicit later editing and `/dice` navigation.

**Checks:** Keyboard/tab order, scroll/zoom, screen-reader description, runtime reduced-motion changes, all animation paused, first-load error and renderer error, frontend route regression. Ensure no command request occurs during browse/pause/reload, including with pending command storage populated.

**Done:** Page works as a quiet ambient homepage and an ordinary accessible project directory.

## W14 — Acceptance, optimization and release readiness

**Inputs:** All tasks. Read PRODUCT acceptance verbatim.

**Owned outputs:** `art/commons/review/final/` evidence, focused fixes coordinated to owners, and final traceability report. Deployment is a separate explicit user action.

**Work:** Run the matrix below in actual local runtime. Compare baseline and final at matching sizes. Measure asset/texture/render budgets and trim inefficient work. Verify migration/rollback behavior and Dice regression. No broad rewrite to chase a synthetic benchmark.

**Done / G2:** Every required row has evidence and a clear pass; no placeholder art, unresolved contact/occlusion defects, missing view, unsupported production appearance, or unverified state migration remains. Art is reviewed at actual display sizes and native scale. Include the ten-minute unattended review from DIRECTION. Record any deviation in PRODUCT/TECH and obtain a concrete decision rather than silently lowering the bar.

## Visual and behavioral acceptance matrix

| ID | Reproducible fixture/action | Evidence and pass condition |
| --- | --- | --- |
| V01 | Place every prop/orientation and each actor frame on calibration tiles at desktop/mobile scale | Native and displayed contact sheets at DPR 1 and 2: root/support error ≤1 logical pixel; no visible float; anchors/trim correct |
| V02 | Walk continuously around all sides and corners of sofa/table/plant; scrub every 50ms near depth crossings | Recording plus stills at before/tie/after: correct partial occlusion, no pops, feet connected, deterministic ties |
| V03 | Walk across every rug edge; place lamp/table on near and far edges | Rugs never cover feet/legs/shadows; projected borders remain on floor |
| V04 | Traverse all permitted perimeter paths and approach kitchen/columns | Rear shell, occluding counter and wall pieces behave correctly; no walking through baked furniture |
| V05 | Gallery of twelve appearances, all four views, all gait frames and idle eye states | Complete component coverage, no seams or wrong-view parts; accessory handedness consistent; planted foot slip ≤1 logical pixel during contact |
| V06 | Record full 180-second program using actual state | Each resident stays within its assigned 60-second window, walks ≤20 seconds, holds ≥10 seconds at window boundaries and returns home; at most one walker, no collisions/wrap jumps, calm pacing, no synchronized breathing/blinking |
| V07 | Two clients, reload at known phase, change scene version and deliver stale response | Matching authoritative layout/appearance and poses within specified clock tolerance; no arbitrary local wandering or stale overwrite |
| V08 | Pause, toggle reduced motion mid-walk, update state while paused | Zero decorative motion/locomotion while paused; steady light; no inaccessible hidden controls; resume follows explicit reconciliation |
| V09 | Hide tab for two minutes; simulate offline >30s; restore connection; test first-load failure | No hidden animation/poll work, no fast catch-up, safe hold, honest status, fallback and navigation usable |
| V10 | 1440×900, 1024×768, 390×844 and 320px-wide viewports; keyboard/touch use | Whole scene fits, no horizontal overflow/layout jump; mobile shelf follows scene with 24–40px content spacing rather than a large empty region; Dice link works, scroll/zoom/keys unaffected |
| V11 | Warm 60-second render run and ten mount/unmount cycles, scene-state refreshes and asset-version swap | Record hardware/browser/DPR, p95 frame time, draw calls, network bytes and decoded residency; no growing timers/instances/textures; budgets in PRODUCT met |
| V12 | Fresh + customized legacy local DB upgrade; accepted walk replay; stale command conflict | Valid new state, preserved custom data/receipts, correct replay/CAS, loopback guards intact, rollback adapter renders |
| V13 | Browse with pending local command already stored; toggle lamp/music through controlled test state | Zero ambient-page POST writes; semantic effects match snapshot; pending command not silently sent or lost |

## Required check commands during implementation

Run only when their owning code changes, using the repository environment:

- Frontend: `cd frontend && npm test -- --run`; `cd frontend && npm run build`.
- Backend: `cd backend && source .venv/bin/activate && python -m pytest tests -v`.
- Migration: `scripts/commons-dev.sh check`; apply only `scripts/commons-dev.sh local-migrate` against the loopback sandbox.
- Visual verification: actual Phaser browser fixtures and recordings as above; current React tests intentionally skip Phaser and do not cover these assertions.

New shared scripts must work on Ubuntu and macOS Bash 3.2. Add no `/proc`, `ss`, `setsid`, credential logging, production endpoints, or changes to the old `jasonkeung.com/dice` deployment. Do not create tests that merely restate implementation constants; use expected geometry, real upgraded state, and observable render behavior.
