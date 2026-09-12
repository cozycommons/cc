# Cozy Room Tile Scene — Technical Specification

## Context

The current branch starts at `a652ea3` (`origin/main`). The Commons home is mounted at [`frontend/src/App.jsx:7-20`](https://github.com/cozycommons/cc/blob/a652ea3/frontend/src/App.jsx#L7-L20), where `/` renders `CommonsHome` and `/dice/*` remains isolated. [`frontend/src/commons/CommonsScene.jsx:61-159`](https://github.com/cozycommons/cc/blob/a652ea3/frontend/src/commons/CommonsScene.jsx#L61-L159) fetches and validates a scene, handles freshness/visibility/reduced-motion policy, and lazy-loads Phaser. The current renderer in [`frontend/src/commons/commons-phaser.js:194-328`](https://github.com/cozycommons/cc/blob/a652ea3/frontend/src/commons/commons-phaser.js#L194-L328) paints a 512×512 room image and only assembles floor tiles in inspector mode; [`frontend/src/commons/world/geometry.js:50-96`](https://github.com/cozycommons/cc/blob/a652ea3/frontend/src/commons/world/geometry.js#L50-L96) uses an isometric diamond projection.

The scene envelope and command API are established by [`backend/commons/schemas.py:11-35`](https://github.com/cozycommons/cc/blob/a652ea3/backend/commons/schemas.py#L11-L35) and [`frontend/src/commons/sceneApi.js:60-109`](https://github.com/cozycommons/cc/blob/a652ea3/frontend/src/commons/sceneApi.js#L60-L109). Collision and pathfinding already exist on both sides: [`frontend/src/commons/commons-grid.js:90-187`](https://github.com/cozycommons/cc/blob/a652ea3/frontend/src/commons/commons-grid.js#L90-L187) and [`backend/commons/scene_service.py:130-183`](https://github.com/cozycommons/cc/blob/a652ea3/backend/commons/scene_service.py#L130-L183). The current shared contract is [`shared/commons/scene-contract-v1.json`](https://github.com/cozycommons/cc/blob/a652ea3/shared/commons/scene-contract-v1.json), and the latest Commons migration is `0011_commons_living_room_layout.sql`.

## Proposed changes

1. **Shared world contract.** Keep `contract_version=1`, `commons-home`, a 16×16 grid, 512×512 logical canvas, and tile-authoritative `tile_x/tile_y` fields. Change the world projection metadata to orthographic square tiles (`tile_width=32`, `tile_height=32`, origin at the first tile center), add a new catalog version and schema version for the room, and retain the old asset IDs for legacy snapshots. Define new room shell blockers, object footprints, allowed orientations, and four cardinal actor views in the same JSON so frontend and backend derive the same occupancy rules.

2. **Projection and collision.** Replace the isometric math in `commons-grid.js` and `world/geometry.js` with shared orthographic conversion and row-based depth. Keep `findTilePath`, `isTileAvailable`, footprint offsets, hidden-object handling, and Manhattan routing. Add explicit bounds tests for shell cells, the doorway, full furniture footprints, and deterministic shortest-path tie order. Update Python `_normalized_to_tile` and `_tile_to_normalized` to match the shared orthographic contract while preserving legacy normalized command acceptance.

3. **Tile renderer.** Rework `commons-phaser.js` into explicit passes: shell/floor tile layer, decorative floor objects, blocking furniture, residents, and semantic effects/interaction overlays. Build the default floor/wall/trim/door tiles in normal mode, not only inspector mode. Position sprites from tile centers plus authored support offsets; compute depth on every movement sample from ground row and stable entity key. Keep candidate preload, snapshot fade/atomic install, visibility, stale, reduced-motion, and cleanup behavior.

4. **Asset catalog.** Replace the current public catalog entries used by the default layout with a new original cozy-room pack under `frontend/public/commons/assets/`. Add metadata for each prop's display size, anchor, footprint, orientation, hit area, and optional effect socket. Add four-direction resident sprite strips with fixed frame bounds and idle/walk frame metadata. Keep legacy paths resolvable for schema versions below the new maximum so customized/older scenes do not fail validation.

5. **Interactive scene controller.** Change the public Commons Phaser initialization to enable scene input, but keep API writes in React/scene API orchestration. Add a small command queue in `CommonsScene.jsx` (or a dedicated `sceneCommands.js`) that computes a local path with the shared collision helper, sends one `walk_actor` command per adjacent step, applies only returned receipts, coalesces stale refreshes, and cancels on Escape. Use the existing client command ID, expected version, idempotency, and pending-command storage rules; never replay pending commands automatically on page load. Object drag/drop and optional rotate callbacks use the existing command kinds and receipt flow.

6. **Backend migration and layout.** Append `0012_commons_cozy_room_layout.sql`; do not edit or renumber prior migrations. Guard the rewrite to the known untouched `layout_version=9`, schema 7, catalog v2 seed so customized rooms are not relocated. Set the new layout version/schema/catalog, authored shell blockers, cozy-room objects, safe actor anchors, and a disabled/resting-only ambient state for direct play. Update `COMMONS_SCHEMA_CONTRACT_VERSION`, the backend fallback contract, and semantic migration fixtures. Preserve IDs, state booleans, service-role boundaries, CAS, receipts, and `/commons` routes.

7. **React/CSS shell.** Keep the existing page chrome and accessible fallback, but give the room frame a square fit that matches the logical world without stretching. Remove obsolete DOM drag styles that imply a separate interactive implementation, add room status/controls text for keyboard and touch, and make the Phaser canvas the primary visible room. The static fallback should use the new generated room-shell asset.

## Testing and validation

- Update pure frontend tests for orthographic round trips, bounds, row-depth, direction mapping, shell blockers, footprints, pathfinding, deterministic entity ordering, catalog metadata, and legacy compatibility. These cover Product behaviors 1–8 and 12.
- Extend backend scene-service tests for contract alignment, tile/normalized parity, new layout migration assumptions, blocked/occupied commands, receipt versioning, and ambient invalidation. These cover Product behaviors 7–11 and 16.
- Update `CommonsScene` tests for accessible top-down copy, initial loading, stale snapshot retention, command queue success/rejection, focus/visibility, and reduced-motion behavior. These cover Product behaviors 9, 13–16.
- Run the existing browser fixture at `/commons-review.html` with the new asset catalog, keyboard movement, click-to-walk, drag preview, and shell collision enabled. Capture a desktop and narrow viewport screenshot for visual review. Browser checks must confirm the `/dice` link still navigates and no console errors occur.
- Run `cd frontend && npm test -- --run`, `cd frontend && npm run build`, the Commons migration contract check, and the backend Commons tests. Run local database migration/verification only through the loopback-guarded `scripts/commons-dev.sh local-migrate` flow when Supabase is available.

## Parallelization

Parallel workers are not proposed for implementation. The projection, contract, renderer, asset metadata, migration, and command queue are tightly coupled and share the same fixture; splitting them into concurrent worktrees would create merge risk without reducing the critical path. The read-only architecture survey can remain separate, but implementation and browser validation should proceed sequentially from this single branch.

## Risks and mitigations

- **Legacy snapshots:** retain old catalog IDs and a compatibility path; only the guarded migration rewrites the untouched default seed.
- **Frontend/backend projection drift:** derive both from the shared JSON and add round-trip tests on both sides.
- **Pixel-art asset registration:** use fixed atlas frames and authored anchors; missing optional assets must not invalidate the shell.
- **Command races:** preserve expected-version/CAS and receipt idempotency; accept only canonical receipt state.
- **Stale ambient schedules:** disable or invalidate schedules when movement/blocking geometry changes and validate candidate programs against the new blocked grid.
- **Browser rendering regressions:** validate the actual Phaser fixture, not only React/jsdom tests, and retain the static accessible fallback.
