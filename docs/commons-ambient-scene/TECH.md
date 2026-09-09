# Technical specification: spatially coherent ambient Commons

Status: selected architecture; implementation is in progress. See [DIRECTION](DIRECTION.md) for decisions and rationale. This document records the contracts as they are implemented and refined.

## 1. Architecture and ownership

Retain the lazy-loaded Phaser renderer and React page. Extract responsibilities from `commons-phaser.js` behind a narrow adapter: `create`, `syncSnapshot`, `setMotionPolicy`, `resize`, `destroy`. React owns fetching, accessible description and project navigation; Phaser owns display objects and rendering. Neither owns a writable world simulation. Ambient browsing exposes no public scene controls; an internal paused policy remains available to deterministic fixtures and future embeddings.

Runtime modules under `frontend/src/commons/`:

| Module | Responsibility |
| --- | --- |
| `world/geometry.js` | Continuous projection, discrete tile validation, support/footprint transforms |
| `world/contracts.js` | Snapshot/manifest validation and explicit legacy adapter |
| `render/asset-registry.js` | Validated orientation/frame metadata and texture lookup |
| `render/grounding.js` | Sprite registration, support points, contact shadows |
| `render/depth.js` | Render passes, depth pieces, deterministic ordering |
| `characters/recipes.js` | Validated recipe IDs mapped to prebuilt character atlas outputs |
| `characters/pose.js` | Walk phase, planted idle, eyes, compatible part selection |
| `ambient/timeline.js` | Pure evaluation of backend schedule at a supplied time |
| `ambient/motion-policy.js` | Pause, reduced motion, visibility and quality policy |
| `render/effects.js` | State-backed light, leaf and steam systems |

Build-time composition lives under `scripts/commons-art/`, with source parts under `art/commons/v2/characters/`. The runtime never imports that source kit or compositor.

Use existing JavaScript conventions; this work does not require a TypeScript migration. Pure functions must not read global time or random state; time, seed, snapshot and manifests are inputs. A scene-specific clock wraps monotonic time. The adapter must remove listeners, timers, textures it owns, and the Phaser instance on unmount, including React development remounts.

## 2. One spatial contract

Keep columns=16, rows=16, logical view=512×512, tileWidth=32, tileHeight=20, origin=(256,180). Introduce names `u,v,h` for continuous ground coordinates and height in logical pixels. Integer `tile_x,tile_y` refer to tile centers, never corners. Tile (0,0) is centered at the origin. A cell extends ±0.5 in each ground axis. The complete floor boundary projects from (-0.5,-0.5), (15.5,-0.5), (15.5,15.5), (-0.5,15.5) to (256,170), (512,330), (256,490), (0,330). Rear walls rise from the two rear perimeter edges; their floor supports and counters have catalogued collision geometry. Validate the shell outline against these corners, not the centers of edge tiles.

Projection, without rounding or clamping:

```
px = 256 + 16 * (u - v)
py = 180 + 10 * (u + v) - h
```

The existing `tileToPixel` normalizes/rounds; retain a compatibility wrapper as necessary but never use it for continuous movement. Validation rejects invalid world coordinates; it must not silently move out-of-bounds input to an edge tile. Define inverse ground projection with h=0 and test round trips on fractional positions as well as corners.

Source art scale `S=3` pixels per logical unit. Rendering at viewport scale `K` multiplies every world coordinate and extent uniformly. Per-object percentages of room width disappear. Art manifests declare original dimensions and scale; texture packing may trim but must preserve original-frame origin and trim offset.

Logical camera coordinates are independent of framebuffer dimensions. Allocate the backing store from measured displayed canvas width/height × effective DPR (capped at 2), and map the 512-unit camera uniformly into it; do not retain a 512px buffer and enlarge it with CSS. Recompute on resize without recreating world state. Keep texture filtering consistent across all packs and inspect pixel-cluster readability at DPR 1 and 2. The source detail ceiling is 1536px; higher backing resolution cannot invent additional detail.

Maintain three independent concepts:

1. **Support geometry:** ground anchor plus visible contact points/patches. For a person, the root between planted feet; for a chair, the center of its support polygon; for a rug, its declared center.
2. **Collision footprint:** occupied tile offsets used by backend placement/path checks. A one-tile pot can have a much wider canopy. A rug has coverage but no blocking footprint.
3. **Occlusion geometry:** render pieces and their ground depth references; it can extend beyond collision cells. Do not derive this from collision or alpha bounds automatically.

Orientation offsets are authored per supported orientation. For this release retain north/south object API values as opaque existing asset variants; do not assume north means a horizontal flip or imply an unimplemented 90-degree rotation. Each variant must supply matching support, footprint and occlusion metadata. Actor facing is a separate domain.

## 3. Versioned asset manifest

Add `shared/commons/scene-contract-v1.json` for projection, semantic geometry, allowed appearance IDs, and supported orientation footprints. Backend and frontend consume this same artifact using paths resolved relative to their modules. Ensure backend deployment packaging includes it; test installation/build resolution. Avoid separate handwritten Python and JavaScript defaults for new-schema state.

Keep texture/atlas details in `frontend/public/commons/v2/manifest.json`, keyed by versioned asset ID. Hash/version references join it to the shared semantic catalog. A deploy must serve old referenced assets until clients on old snapshots expire. No user-supplied asset URL is fetched from state; resolve allowlisted IDs only.

Illustrative asset record (worker supplies actual measured points and complete frames):

```json
{
  "id": "lamp.walnut.v1",
  "sourceScale": 3,
  "layer": "world",
  "orientations": {
    "south": {
      "frame": "lamp-walnut-south",
      "originalSizePx": [144, 240],
      "groundAnchorPx": [72, 222],
      "supportPoints": [{"worldUV": [0, 0], "sourcePx": [72, 222]}],
      "coverageCells": [[0, 0]],
      "blockingCells": [[0, 0]],
      "depthPieces": [{"pieceId": "body", "frame": "lamp-walnut-south", "originalSizePx": [144, 240], "trimOriginPx": [0, 0], "depthOffset": 0}],
      "shadow": {"kind": "contact", "radiusU": 0.25, "radiusV": 0.25}
    }
  }
}
```

`supportPoints` pair local u/v offsets relative to the entity anchor with measured contact pixels in the original source frame. At h=0, the projected relative world point must match `(sourcePx-groundAnchorPx)/S` within one logical pixel. Annotate contact patches when a foot or pedestal occupies an area. Animated actors also declare per-frame planted-foot markers and contact-phase labels; a lifted foot is not incorrectly tested as ground contact. `depthPieces` include stable piece IDs, original bounds and trim origins; offsets are logical ground-depth units. Pieces preserve the full illustration registration and cannot stretch or shift independently. Recomposition must match the source illustration pixel-for-pixel before depth insertion. The root source pixel lands exactly at projected ground position: for an untrimmed frame, its top-left is `project(u,v,0) - groundAnchorPx/S`. Trimmed atlas frames apply trim offsets before that equation. Do not guess the contact point from the bottommost nontransparent pixel, because shadows, fringe and extended legs make that unreliable.

The asset pipeline validates frame existence, dimensions, anchors within original bounds, footprint bounds at placement, disjoint/complete depth masks, source scale, supported variants, and catalog/manifest hash agreement. It emits a contact-sheet proof with the floor diamond, root crosshair, support points, collision cells and occlusion pieces. Manually inspect visible contact; numerical validity alone is insufficient.

Art production uses editable layered 2D sources on the shared orthographic projection template, followed by deterministic atlas export. The existing Blockbench room is a proportions reference only; no 3D pipeline is required. Independent AI-generated images are concept material until cleaned up and registered to this template. Retain editable sources, export settings, provenance, and a manifest per delivered pack. Draw shadows as separate layers and assign projected supports before detailing an asset. Production exports must pass registration checks rather than inheriting arbitrary transparent padding.

## 4. Render passes and occlusion

The renderer uses these strict passes:

1. Background and rear architectural surfaces.
2. Floor tiles, then floor decals/rugs, with explicit decal order and stable ID ties.
3. Ground-only light pools and contact shadows, clipped to the floor/rug surface where needed.
4. Depth-sorted world pieces: architecture that can occlude residents, furniture, actors, supported tabletop details, and owner-bound opaque effects.
5. Sparse translucent atmosphere with explicit ownership/masks; it cannot turn into a global overlay hiding foreground objects.
6. Development overlays; React controls are outside the canvas.

A shell image containing an oven, counter, window ledge or front wall cannot remain entirely behind everything. Extract its occluding pieces into pass 4. Physical counter footprints block traversal, but must not be inflated to conceal rendering defects. The new shell export must have an empty floor; do not paint a second floor under a mismatched tile layer. Rugs use pass 2 irrespective of y or movement blocking.

For pass 4, sort by continuous ground depth `d=10*(u+v)+depthOffset` and deterministic `(entityId,pieceId)` ties. Actor render parts are composed into one registered pose, so outfit layers never interleave with another entity. Contact shadows do not contribute to world depth. Height does not change an entity's ground sort key.

One anchor is permitted only for assets that pass every traversal fixture. Wide furniture must use **authored occlusion pieces**: disjoint alpha masks of one original-frame illustration, each registered to a ground-depth support boundary. Export components such as a table's near apron/legs and farther body as needed, with explicit offsets. Do not split an image into arbitrary horizontal strips or assign the entire table to its nearest leg: those shortcuts break side traversal. Each opaque pixel belongs to exactly one piece to avoid dark seams. An actor can therefore draw between pieces of one object while its own body stays coherent.

The vertical-slice worker must prove the chosen pieces using the sofa's full perimeter and a tall plant. If a prop cannot pass with this method, re-author its geometry/pieces before broad asset production; do not ship a known broken side view or add per-character positional exceptions. Initial layout avoids interpenetrating furniture. No dynamic table-walking, under-table traversal, or seated interleaving is required. Small non-stateful mugs/books are baked into their furniture piece. State-backed effect sources use declared sockets on that piece; no general attachment/ECS system is introduced.

Depth is recalculated during every movement sample, not just tile arrival. Use stable ties without an arbitrary actor-on-top bias. Test identical scene snapshots with shuffled entity insertion order. Shadows remain under their owner's support points and above rugs; no pre-baked perimeter glow substitutes for a contact shadow. Translucent steam is emitted from a declared local socket and ordered/masked with its source so it cannot appear through unrelated near furniture.

## 5. Composable characters

A single `resident-v1` rig defines a 144×240 source frame (48×80 logical units), root `(72,222)` source pixels, and a shared pose/sockets table. These bounds and root are fixed for worker implementation. A demonstrated calibration failure is resolved by the integrating lead before any change propagates to other components. All frames and parts use identical original frame bounds; atlas trimming cannot alter registration.

Four view keys map unambiguously:

| World move | View | Description |
| --- | --- | --- |
| +u (screen down-right) | `front_right` | Face/chest visible, walking toward lower right |
| +v (screen down-left) | `front_left` | Face/chest visible, walking toward lower left |
| -u (screen up-left) | `back_left` | Back visible, walking toward upper left |
| -v (screen up-right) | `back_right` | Back visible, walking toward upper right |

Stationary actors retain the schedule's view. There are no diagonals in logical navigation. Convert legacy facing through one documented adapter verified against existing movement semantics. Do not overload furniture orientation names.

Each view supplies eight walk frames (contact, recoil, passing, rise, opposite contact, recoil, passing, rise), one planted idle base, one subtle glance pose, a breathing pose delta/layer transform, and open/half/closed eye masks for visible eyes. A rear view has no eye mask. Left/right mirroring is allowed only for a component explicitly declared symmetric, with tested sockets and light direction; asymmetrical hair/accessories/outfits need both views.

Composition channels: rear hair/accessories → rear limbs → body/skin → footwear/legs → outfit → front limbs → face/eyes → front hair/accessories. This is a starting list: manifest arrays per direction and pose are normative because the rear arm and hair order changes. Opaque coverage masks prevent clothes from exposing unwanted body pixels. Every component declares rig version, supported views/poses, palette slots and compatibility constraints. Reject incomplete combinations at validation; never silently mix a front-only part into a back pose.

Appearance data is a small allowlisted descriptor, e.g. rig, body, skin palette, eyes, hair style/color, outfit, shoes, accessory and deterministic variant seed. Ship at least two hair styles, three outfits, three skin palettes, two footwear choices and one optional asymmetric accessory, covering all required views/poses. Twelve valid combinations must be displayed together in a proof sheet; include each component at least once and include dark/light palette contrasts and the asymmetric accessory in all views.

The build-time compositor deterministically exports each selected recipe: four-view walk atlases, planted lower-body/upper-body idle layers, glance poses, eye masks and socket metadata. Hash the full appearance descriptor plus rig/component versions into the output ID; the semantic catalog and runtime manifest must resolve the same ID. Package only the three deployed residents' outputs, not all component combinations. A developer gallery build exports twelve combinations through the same pipeline. A thirteenth recipe uses data and the existing compositor with no renderer edits.

Build fails on incompatible or incomplete components. Runtime validates the snapshot recipe ID against the loaded catalog before displaying it. If a referenced output fails to load, retain the last valid scene or use the static fallback on initial load; do not silently substitute a different live resident. Load each required texture once and release it with its owning scene/asset pack. Runtime pose evaluation only selects frames and applies registered idle/eye transforms; it does not generate atlases or manage an appearance-combination cache.

On each edge, ground position interpolates linearly using the authored edge duration. At an adjacent-edge boundary, position is exactly the common tile center; view changes to the outgoing edge and normalized gait phase carries forward without reset. At a hold, the view is the declared hold view. Start/stop transitions blend limb poses for 100–160ms without changing route position, edge duration, or the planted root; settle into the nearest compatible contact pose at arrival. Avoid whole-body position easing at tile boundaries. Walk phase derives from distance traveled and a calibrated stride, not wall-clock frame count alone. Freeze a stride calibration at the vertical slice, then test that planted feet don't slide more than 1 logical pixel relative to floor during the contact portion. Breathing moves upper-body layers about a shared waist socket; it must not scale the whole sprite and float the feet. Blink timing uses a seeded per-actor event stream. Pausing freezes event phase; reduced motion removes all idle transforms and blinking.

## 6. Backend state and timeline

Existing GET returns `{id,layout_version,version,state,updated_at}`. Preserve these fields; add a response-level `server_time_ms` sampled at response creation, not persisted as scene content. Keep `version` for CAS state revisions. New state uses `schema_version=7`, a `catalog_version`, actor `appearance` descriptors, and an `ambient` program. `layout_version=9` denotes the current authored living/dining composition; layout 8 remains the previous evening composition for rollback and compatibility. Metadata-only upgrades of customized layouts retain their layout identity.

Actor `tile_x,tile_y` remain the canonical home/rest anchor with derived legacy x/y compatibility fields. They are NOT the current scheduled pose when ambient roaming is active. Consumers call `evaluateAmbientPose(snapshot, actorId, time)`; do not place visible ambient residents directly from home anchors. Snapshot validation explicitly checks that every home anchor is safe.

Ambient state is a tagged union. Disabled state is `{enabled:false, revision, reason}` with reason in `legacy`, `invalidated`, or `resting_only`; evaluation returns each validated canonical home and facing. Enabled state has `enabled:true` plus all program fields below. Every enable/disable/replacement increments ambient revision within a new CAS scene version. Missing ambient data is interpreted only by the explicit legacy adapter, never as permission for client roaming.

Ambient program shape:

- `revision`, `epoch_ms` (UTC), `cycle_ms=180000`, `seed`, and per-actor ordered segments.
- Segments are `hold` with duration, tile and facing, or `walk` with ordered adjacent tile-center waypoints and explicit per-edge durations. Every actor's durations sum exactly to the shared cycle. Every segment boundary is continuous: hold tile equals incoming/outgoing walk endpoint, adjacent walks share their boundary point, and first/last position agrees; wrap never teleports. No client pathfinding chooses new ambient destinations.
- The compiled program stores paths, not just target tiles. Authoring may use the existing pathfinder, but backend validation checks the actual compiled program against current geometry.
- The shipping score follows the three 60-second resident windows in DIRECTION, with no more than 20 seconds walking per actor and safe home returns. Only one walking actor is allowed at a time, with all other residents holding at safe positions. Avoid seat/stand transitions in this release; use standing reading/listening/window-watching poses.
- Seed and program revision determine decorative variation; semantic light/music values still come from each object's persisted state. Asset metadata contains sockets and effect styles, not object on/off truth.

Use these exact segment keys in the shared contract: `kind`, `duration_ms`, `tile`, `facing` for holds; `kind`, `waypoints`, `edge_durations_ms` for walks. Tiles are `[u,v]` integer pairs. A walk's duration is the sum of its edge durations; array length is waypoint count minus one. Facing is derived per walk edge. Program actor keys must exactly match the actors participating in the scene; all remaining actors need explicit hold-only tracks, not hidden client defaults.

Minimal **empty-room test fixture**, not the final authored room or production seed:

```json
{
  "enabled": true,
  "revision": 1,
  "epoch_ms": 1800000000000,
  "cycle_ms": 180000,
  "seed": 42,
  "actors": {
    "host": [
      {"kind": "hold", "duration_ms": 176400, "tile": [4, 4], "facing": "front_right"},
      {"kind": "walk", "waypoints": [[4, 4], [5, 4], [6, 4]], "edge_durations_ms": [900, 900]},
      {"kind": "walk", "waypoints": [[6, 4], [5, 4], [4, 4]], "edge_durations_ms": [900, 900]}
    ]
  }
}
```

This fixture intentionally has one actor to isolate evaluator behavior; the final three-resident score is W08's concrete output. Validation must reject it if the surrounding snapshot declares additional residents without tracks.

Compilation/validation checks all tile coordinates, adjacency, positive bounded durations, sum/loop continuity, support collisions, route edges, holds and inter-actor occupancy across the complete repeating cycle. With only one walker at a time, test its entire path against every other resident's hold tile and reserved footprint; include wrap intervals and a 0.2-tile visual clearance margin. Reject a schedule whose timing overlaps walk intervals. Later multi-walker support requires swept edge reservations and is explicitly deferred.

Visible GET polling uses the existing eight-second cadence, with at most one request in flight. Focus/online triggers coalesce with it; hidden tabs suspend it. Public GET is read-only. The backend does not tick every frame or persist every step. A client's phase is the nonnegative mathematical modulo of `(estimatedServerTime - epoch_ms)` by `cycle_ms`, including time before epoch; JavaScript `%` alone is insufficient. Establish server-time offset using request start/end midpoint; retain a monotonic anchor between responses. Measure uncertainty as at least half RTT. If uncertainty exceeds 500ms, finish at most the current validated edge and hold at its endpoint, or use validated home anchors on initial load, until a reliable sample arrives. With RTT ≤200ms, two clients should evaluate poses within 0.25 tile at the same measured server time; pure evaluation at identical input time must match exactly.

Reconciliation rules:

- Initial load: validate snapshot/catalog, then show the current scheduled pose; no entrance teleport animation.
- Same revision refresh: retain continuous local monotonic time. Slew clock errors ≤100ms over two seconds; larger errors use the correction policy below. Never restart the idle/walk cycle on polling.
- New revision: validate and preload the complete candidate snapshot before any displayed entity changes. Geometry/catalog changes use a 200ms scene fade-out, atomic whole-snapshot installation, and 200ms fade-in. Actor-only program/time corrections can use the same timings for affected actors. Never display a mixture of old geometry and new resident poses or tween through walls. A failed preload retains the previous valid snapshot and does not reset freshness. An internal paused policy queues the candidate; reduced motion applies an atomic static-home replacement without fading. Rapid updates coalesce to the newest valid candidate.
- Ignore older versions and responses from superseded requests. Validate schema/catalog separately from version; unknown newer schemas show last valid state or fallback, not partially interpreted state.
- After 30 seconds without a usable refresh while visible (compatible schema/catalog, validated geometry/program, and a reliable time sample; HTTP 200 alone does not qualify), finish at most the current edge to its validated endpoint, then hold all actors and indicate connection loss quietly. Decorative state-bound effects may remain frozen or steady, never imply new semantic changes.
- If an embedding or development fixture supplies an explicit paused policy, it freezes the entire last rendered snapshot and presentation-time anchor, including object/light semantic appearance. Fetching may queue the newest valid snapshot, but no scene object fades, moves or changes until the policy is released. This avoids mixing a frozen actor with newly moved furniture. World time continues on the server; release atomically installs the newest compatible snapshot and uses the correction policy to reach its current phase. Reduced motion instead presents safe canonical home anchors, with no scheduled locomotion or refresh-driven route teleportation; semantic snapshot changes apply atomically without motion unless the internal paused policy is also active. Hidden tabs stop ticking/polling; return fetches a fresh snapshot before resumed locomotion. Project navigation never waits for scene recovery.

This defines a backend-backed presentation timeline, not a general multiplayer simulation. Future interactive commands must explicitly suspend/recompile affected ambient programs. For now, any successful existing command changing actor position, object placement/orientation, or blocking state first builds the candidate world (`walk_actor` updates that actor's home/facing), validates all resulting home anchors against blockers and each other, then atomically stores that world and a disabled ambient program with incremented revision. Invalid candidates change neither version. Displayed residents return to their resulting safe home anchors; re-enable only after a validated program is authored. Nonblocking on/off states may preserve the program. Placement validation must reject new blockers on any home anchor as well as ordinary occupied cells. Treat program invalidation as part of the same CAS transaction.

Do not auto-replay an old locally queued command on ambient page load. Retain it for a later explicitly enabled editing workflow; public ambient mode makes zero command requests. Do not silently drop persisted user intent or execute it in the background.

## 7. Migration and compatibility

Append a Commons migration after the current head; do not edit `0001`–`0008`, Dice migrations, sandbox guards, RLS or service-role boundaries. Use separate additive metadata and authored-layout changes so rollback can select the old renderer/assets while retaining existing snapshots.

Before applying the new layout, distinguish untouched legacy seed from customized rooms by exact known entity positions/orientations/state, not `version==0` alone. Metadata-upgrade customized objects without moving them only if every legacy reference maps losslessly to supported catalog geometry and all resulting anchors validate. Otherwise retain their legacy schema/catalog and a compatible static legacy renderer/adapter; do not label an incompatible layout schema 7, change its footprint, or relocate its objects to force validation. Only apply the new composition to a matching untouched seed; otherwise keep layout and provide a validated resting-only program until a new safe route/layout is explicitly selected. Missing appearance IDs receive deterministic defaults for the three existing stable actor IDs. Preserve object IDs, state booleans and command receipts. All upgrades must be repeatable and validated against the resulting state.

Update Commons migration contract version and extend semantic fixture validation; the existing SQL attestation of table/function presence is insufficient. Exercise fresh database migration and upgrade of a deliberately modified legacy layout on loopback only. Keep all `/commons` and `/dice` paths, service-role-only writes, expected-version conflicts and receipt IDs intact.

Because this release touches command invalidation, add a regression for retrying an already accepted walk through the actual API: current Python validation can run before RPC receipt replay and reject the already-completed step. Correct receipt lookup/validation sequencing without accepting a reused ID with different payload or bypassing CAS for new commands. This is a bounded compatibility repair, not authorization to redesign authentication or commands.

Rollback: select the previous renderer/manifest and disable new ambient programs through a compatible read adapter; retain immutable prior assets. Never rollback by renumbering migrations or destructively restoring old JSON over user changes. If the old renderer cannot read new descriptors, the adapter returns legacy asset IDs/home anchors. Document and test this path before rollout.

## 8. Validation interfaces

Build development-only deterministic scene fixtures with injected snapshot, seed, presentation time, motion policy and viewport. Include contact/depth/footprint overlays and a manual time scrubber. These controls are verification tools, not public product UI. Tests must exercise actual Phaser rendering in a browser because current React tests skip its initialization.

Required pure tests: fractional projection, strict bounds, manifest registration/trim, orientation footprint parity, stable sort keys, deterministic character selection, timeline boundaries/wrap and rejection, monotonic reconciliation and cleanup. Required backend tests: actual migrated seed, customized upgrade, catalog parity, route safety, program invalidation, stale CAS, replay and read-only browsing. Required visual evidence is detailed in PLAN. The current branch has implemented the geometry, catalog validation, ambient evaluator, passive scene, timing/freshness policy, renderer adapter, calibrated resident sizing, and additive seed migrations; the remaining art and browser acceptance work stays tracked in PLAN.
