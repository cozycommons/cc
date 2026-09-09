# Evidence and specification audit

## What was inspected

Baseline commit `83c9bafe2759cef0728a1446245fe2e46bead56c`. Working tree was clean when planning began. The planning deliverables are new Markdown documents under this directory; no implementation, asset, migration, database, or deployment change was made.

Read-only frontend and backend research was delegated, then the proposed contracts were reviewed independently for concrete gaps. The primary author inspected scene/page code, actual room images and the directional concept sheet. Initial browser inspection was blocked by the locked Mac. After the user unlocked it, a follow-up inspected the live `http://localhost:8080/` scene (displayed state version 25), including screenshots at DOM-verified 1440×900 and 390×844 CSS-pixel viewports, naturally changing ambient poses, and the G grid overlay. Screenshots are in the conversation tool evidence; no video file or exhaustive traversal recording was produced. The browser reported DPR 0.75, so requested viewport overrides were calibrated against actual `innerWidth/innerHeight`; these are not DPR 1/2 acceptance tests. The grid and viewport were restored afterward. No furniture/actor commands were issued. W01 still owns repeatable saved baseline recordings and controlled traversal evidence.

## Follow-up live visual review

Observed directly in the existing local scene, without editing its state:

- **Rug occlusion:** a sampled maker pose beside the record console loses most of its lower legs behind the rug edge. Other sampled poses show the feet again. This visually corroborates the floor-pass defect; future V03 must use this exact rug/console approach as a regression witness.
- **Shell/grid alignment:** the G overlay's back vertex falls near the console/sofa area rather than the painted rear floor corner, and the side boundaries do not coincide with the room's painted floor boundary. Correcting sprite anchors alone cannot fix this. The shell, floor and navigation domain must share a calibrated template.
- **Composition:** the sofa crowds the sink/counter; the console cuts across the listening area; the red armchair, green loveseat and palm form a dense overlapping cluster. The large table dominates the foreground while its chair sits apart. These are visual composition observations, not a claim that every pair violates backend collision.
- **Floor treatment:** high-contrast alternating square/diamond textures create a patchwork that competes with residents and furniture. Use a lower-contrast, coherent floor material with continuous projected seams.
- **Resolution:** at verified 1440×900 CSS viewport, the live canvas has a 512×512 backing store and a displayed width of approximately 850.44 CSS pixels. This confirms the need to decouple logical coordinates from display resolution.
- **Mobile flow:** at verified 390×844 CSS viewport, document width is also 390 (no horizontal overflow in this sample). The full room fits, but a large unoccupied vertical region separates it from the Dice project card. Tighten the content flow rather than shrinking the room further.
- **Existing strengths:** the warm windows, dark wood, upholstery, and recognizable resident silhouettes already communicate the intended mood. Preserve these while improving spatial registration, material consistency and composition.

The sampled resident poses establish that ambient movement is active, but do not quantify gait speed, blink timing, collision safety or all occlusion paths. Those remain implementation validation tasks, not claims from screenshots.

## Current-state findings

| Finding | Inspected evidence | Design consequence |
| --- | --- | --- |
| Warm domestic mood already exists | `frontend/public/cozy-commons-room-empty.png` visually inspected: furnished cutaway, dark wood, amber lamps, plants, rich upholstery | Preserve warmth and domestic detail, rebuild spatial consistency |
| Current shell includes substantial painted kitchen/floor geometry | `frontend/public/commons/cozy-commons-room-tile-base.png` visually inspected | Export an empty-floor shell and separable occluding architecture |
| Character concept has appealing detail but is not a production rig | `art/commons/concepts/host-direction-sheet-v2.png` visually inspected; `art/commons/README.md` distinguishes prototype from finished pack | Use as art direction; author registered, composable parts |
| Every sprite uses texture bottom as contact | `commons-phaser.js:470` origin `(0.5,1)`; `:498` width-percentage scaling; `commons-assets.js:43` sizes | Explicit source anchors, support markers and shared art scale |
| Rug has no separate drawing pass | `commons-phaser.js:100` entity depth and `:390` depth update; `commons-grid.js:20` nonblocking rug footprint | Decouple floor decoration from collision and world depth |
| Actor art lacks true four-view animation | `commons-assets.js:19` four-frame strips; `commons-phaser.js:453–465`, `:500`, `:696` sheet/flip behavior; research agent inspected actual host strip | Four view families with a composable pose/part contract |
| Ambient motion is brisk and client-local | `commons-phaser.js:27` routes; `:607–655` scheduling; `:702` 155ms steps and per-tile easing | Validated backend timeline, slow distance-consistent movement, long rests |
| Ambient actor visual and canonical positions differ | `commons-phaser.js:505–529`, `:628–637` local actor map/path replacement | Explicit home-versus-evaluated-pose semantics and complete route validation |
| Grid projection rounds input | `commons-grid.js:55` uses normalized tiles | Separate continuous projection from discrete validation |
| Motion/accessibility policy is incomplete | `commons-phaser.js:608` reduced-motion route check versus `:568–586` looping effects; `commons-scene.css:19` touch action; `CommonsScene.jsx:292` global keys | One motion policy, passive input, pause and reduced-motion reconciliation |
| Current tests cannot establish visual correctness | `CommonsScene.jsx:256` skips Phaser in test mode; asset/grid/React tests inspect metadata and commands | Actual browser fixtures and full-motion visual gates |
| Backend already owns durable scene and command versions | `backend/commons/schemas.py`, `routes.py`, `scene_service.py`; migration `0001_commons_scene.sql` | Preserve envelope/CAS/receipts, add compact timeline and catalog |
| Current seed is layout 7/schema 6 | Migrations `0003`–`0007`; `0008` changes service-role read grants | Recheck head, append new migration, distinguish three kinds of version |
| Footprints exist but are not art/occlusion metadata | `0005_commons_furniture_footprints.sql`; duplicated frontend/Python defaults | Shared semantic catalog plus render manifest; per-orientation validation |
| Shell blockers use upper grid edges | `0006_commons_room_shell_blockers.sql`; seed repairs in `0007` | Validate redesigned architecture and exact seed, not only legacy blockers |
| Replay validation has a sequencing risk | `scene_service.py` applies command before RPC receipt replay; SQL receipt logic in `0001` | Accepted-walk API replay regression if command plumbing changes |
| Attestation is structural | `commons_schema_contract.sql` checks tables/function/RLS | Add semantic migrated-state/route/catalog validation |

Source line numbers describe the inspected baseline, not future locations after refactoring. Paths without a prefix in the frontend rows are relative to `frontend/src/commons/`.

## Refinements from independent review

1. Backing-store dimensions now follow displayed size and capped DPR, so detailed source art is not crushed into the old 512px canvas before display.
2. Support points include measured source contact pixels; depth pieces include original registration and trim metadata. This makes calibration reproducible.
3. Four-view direction mapping, edge interpolation, corner phase continuity and stop behavior are explicit.
4. Disabled ambient state, command invalidation, home-anchor validation and usable-snapshot freshness have defined serializable behavior.
5. Pause freezes the entire displayed snapshot and queues updates; reduced motion uses static home poses. This avoids incompatible frozen actors/new furniture and refresh-driven route teleportation.
6. Customized legacy scenes upgrade only with lossless catalog mapping; otherwise they stay on an explicit legacy/static compatibility path.
7. Multi-piece occlusion is the selected implementation technique requiring the vertical-slice proof. It is not presented as already proven for every existing prop.

## User-request coverage

| Requested outcome | Where the detailed instructions live | Specification audit |
| --- | --- | --- |
| Start with high-level end-to-end strategy, then refine | README strategy/decisions; PLAN dependency chain; review refinements above | Present |
| Draft detailed spec and plan; do not implement | PRODUCT, TECH, PLAN; docs-only final diff | Present; no implementation performed |
| Small subagents can execute later | PLAN W01–W14 with inputs, owned paths, checks, done conditions and universal worker packet | Present |
| Lively, clean, consistent, cozy ambient world | PRODUCT experience, art palette/proportions/composition and motion budget | Present with visual gates |
| Object bases connect to their tiles | PRODUCT G1/G2; TECH geometry/manifest/contact marker contracts; V01 | Present |
| Correct front/behind layering, including rugs | PRODUCT G3–G5; TECH passes/depth pieces; V02–V04 | Present, visual proof required during implementation |
| Composable new characters | TECH rig, component inventory, compatibility and build-time recipe exports; W05/W06 | Present |
| Front/back/left/right and walking | TECH four-view mapping and eight-frame gait; V05 | Present |
| Breathing and blinking | PRODUCT C3 and TECH pose/motion policy | Present with timing and planted-root rules |
| Stardew/Pokémon feeling with more detail | PRODUCT original-art direction, scale/material/character guidance | Present without copied assets |
| Backend-backed world with later interactivity | TECH catalog/state/timeline/migration/command invalidation; W09–W11 | Present; no per-frame writes |
| Slow, breathing tempo and less interactivity | PRODUCT timing/rest priorities, passive mode; W10/W13 | Present |
| Freedom to redesign | New coherent shell/prop/character pipeline, retained engine with replaced rendering assumptions | Present |

## Completion boundary

This audit verifies the **planning deliverable**: coherent, detailed instructions and an executable dependency/acceptance plan. It does not claim that future rendering, timing, migration or performance criteria already pass. The listed build/test/migration/browser commands are future worker instructions and were not run for this documentation-only task, apart from the follow-up live browser inspection described above. The art proportions, framebuffer behavior and multi-piece occlusion require G1 evidence before implementation is expanded; performance and full-room aesthetics require G2 evidence.

## Direction-setting pass

The user requested that the lead make the major product/architecture choices. Added DIRECTION as the decision authority and updated all consumer specs, rather than leaving competing options for workers. Selected one fixed-evening authored room; a layered 2D art pipeline; build-time recipe composition; backend-authored routines with no simulation daemon; whole-snapshot pause/update behavior; steady lighting; reduced clutter; and an expanded four-direction/full-floor G1 proof. Runtime character generation/cache work was removed from TECH and W06. G0 now explicitly serializes decisions already made.

The shipping score now permits at most 20 walking seconds per resident in separate minute windows, with home returns and quiet boundaries. All three residents and visual polish are release requirements. The exact art-compatible coordinates and tiny pose amplitudes remain controlled calibration work, not unresolved product/architecture decisions. No live implementation or database state changed in this pass.
