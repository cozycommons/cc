# Direction and major decisions

Status: selected direction; implementation is in progress. These decisions replace the earlier open-ended choices and remain the source of truth for the unfinished art, renderer, and acceptance work.

## Product north star

Cozy Commons is a small, inhabited home on the web for the things we make. The room is the primary experience; project links are useful doors out of it. A visitor should find it beautiful paused, comfortable to leave open for ten minutes, and rewarding to glance at occasionally.

Build **one authored evening common room with three recognizable residents**. The scene is always evening, with warm interior lamps and quiet cool windows. No time-of-day controls, quests, progress indicators, public editor, audio, or visitors represented as characters in this release. Pause is the only scene control. The room does not need engagement mechanics to justify its existence.

## Selected decisions

| ID | Decision | Reason and worker consequence |
| --- | --- | --- |
| D01 | Ship the complete ambient room, including three residents and their routines, as one release | A technically correct but sparsely animated demo misses the product. All listed product requirements are release requirements. |
| D02 | Keep React, Phaser and the existing API; use a 2D runtime | The defects are spatial/art/state contracts. An engine rewrite would not resolve them by itself. No new ECS, physics engine, realtime service or simulation daemon. |
| D03 | Preserve the 16×16 world and 32×20 projection; redraw the shell to it | Geometry is the source of truth. No camera/grid warping to rescue independent artwork. Outer cell boundaries, not outer tile centers, define the floor perimeter. |
| D04 | Use a layered 2D raster art pipeline with one projection template and source scale 3 | Editable registered layers are the production source. Blockbench remains a proportions reference; 3D conversion is not a prerequisite. Independent generated images are concept inputs and require registration/paint cleanup before production. |
| D05 | Use explicit floor passes and authored furniture occlusion pieces | Rugs always remain underneath residents and furniture. Wide objects need actual occlusion design. G1 proves the approach; workers cannot substitute actor-specific offsets or hide defects by blocking formerly required paths. |
| D06 | Assemble character recipes at build time | Three deployed residents do not justify browser-side atlas generation and cache lifecycle complexity. A reusable compositor exports any valid recipe; new characters require data/art, not renderer changes. |
| D07 | Backend stores a validated authored timeline; client evaluates its pose | This gives the world continuity without per-frame writes, local random roaming, or an always-running simulation server. It remains an explicit foundation for later interactions. |
| D08 | Freeze the complete displayed snapshot when paused | Incoming furniture cannot suddenly intersect a frozen resident. Queue updates and install a coherent snapshot on resume. Reduced motion uses safe static homes. |
| D09 | Preserve customized legacy layouts through an explicit static compatibility path | The redesign must not silently reset existing state. New-schema art/geometry is used only after a lossless mapping validates. Public editing is not part of this release. |
| D10 | Review visual integration before scaling production | Every asset/character worker starts from the same approved art slice and contracts. Final aesthetics are evaluated in the live room, not just isolated contact sheets. |

## Composition I want

The listening nook is the focal point: rust sofa, woven rug, compact record console and low table. It reads as a place where someone could settle in. The shared worktable is smaller and subordinate, with paired seating and a restrained book/mug arrangement. The window corner holds olive seating and a tall plant with room around its silhouette. Kitchen surfaces remain accessible-looking and visibly separate from the sofa. The front floor provides relief and circulation, not another crowded seating cluster.

Do not require every existing prop in the new authored layout. The red armchair and bar stool are omitted from that layout; retained legacy IDs/assets continue through compatibility. Two chairs at the shared table use separate stable instance IDs. Avoid adding decorative clutter to fill empty areas. Use wood floor planks with coherent seams and narrow tonal variation; the rug provides the strongest floor pattern.

Residents have a purpose, even without interaction:

- **Host:** ochre jacket, listening near the record nook; an occasional short walk to check the room.
- **Maker:** muted blue, attending the worktable; a small head glance and a short break toward the window.
- **Neighbor:** grey-haired silhouette, moss/rust accents, quietly observing the window/plant corner; a brief unhurried change of viewpoint.

Use distinct resting facing/posture recipes and three different timing seeds. Do not deliver three people facing the viewer and pacing short loops together. The kit includes one subtle glance gesture usable by each resident; a held book, sitting, or page-turn system is not required. Future sitting requires support/seat anchors and its own acceptance slice; it must not be faked by floating a standing sprite over a chair.

## Tempo and authored score

Use a shared three-minute cycle. Host movement belongs in seconds 0–60, maker movement in 60–120, neighbor movement in 120–180. Each window contains at most one short outing (out and return, with an optional intermediate hold), no more than 20 seconds total walking for that resident, and at least 10 seconds of stillness at both window boundaries. Path lengths/durations come from the validated layout; unused time becomes a hold. All actors return to their canonical home by their window's end. This stronger rest requirement supersedes the earlier 75% minimum for the shipping score; 75% remains only a broad rejection threshold for test programs.

Walk edges default to 1000ms. Tune within 800–1200ms only to match the common gait. No scene-wide pulsing. Lamps remain steady; only one leaf cluster and one optional state-backed steam source move besides the residents. These effects are subordinate to the art, and all obey pause/reduced motion.

## Architecture boundary

Authoring/build produces the catalog, registered art, character recipe outputs, exact layout and compiled routines. The backend validates and persists semantic state plus versions. The frontend validates a complete snapshot, resolves a matching immutable asset pack, evaluates time, and renders. Dependencies flow in that direction; renderer state never becomes canonical state.

Runtime keeps current snapshot, an optional pending snapshot, asset handles, and presentation-clock state. It does not maintain a second navigation simulation. GET polling stays at the existing eight-second visible cadence; requests never overlap. Focus/online recovery coalesces with an in-flight request. No polling while hidden, no POSTs from ambient mode, no WebSocket dependency.

Character composition is an offline pure operation: recipe + rig/components + asset version → deterministic atlas and manifest. Shipping output contains the three selected recipes. Adding a thirteenth character follows the same build path; a developer gallery proves twelve combinations. Runtime selects prebuilt recipe output and animates the registered pose/eyes/upper-body layers. Do not send the entire combinatorial source kit to the browser.

For scene updates, prepare all required assets and validate the candidate before changing the displayed world. A geometry/catalog replacement swaps the complete snapshot between a short scene fade-out/fade-in; an actor-only clock correction can fade that actor. Never mix versions while assets load. Pause queues the candidate; reduced motion swaps without a fade. Loading failure retains the previous valid snapshot and reports the failure quietly.

## Decision authority and gates

Workers may choose local names, internal helper structure, packing layout and brush details that satisfy these contracts. The integrating lead owns changes to product scope, projection, art scale, rig registration, state meaning, renderer strategy, performance budgets and compatibility. The lead resolves a discovered contract problem and updates all affected docs/fixtures before dependent workers continue; routine implementation choices do not require user permission.

G0: serialize the selected contracts and fixtures. Do not ask a worker to reconsider engines, world shape or product purpose.

G1: one complete four-direction walking resident, rug, sofa, table, plant, and the full calibrated floor/shell outline. Prove registration, side/corner depth, gait, and native/displayed pixel treatment together. Approve a paused composition and a motion recording. This is a proof of the selected architecture, not an invitation to ignore failure. If the technique cannot meet the fixtures, the lead must revise it before proceeding; do not reduce acceptance or quietly change projection.

G2: the complete room and three-minute score, desktop/mobile behavior, real backend state, failure recovery and measured budgets. The lead reviews a ten-minute unattended viewing session as well as the deterministic tests. No demo-only fallback may substitute for the actual scene at this gate.

Only local visual calibration remains adjustable within the prescribed ranges: precise furniture coordinates inside the named zones, color ramps, component drawings, gait stride and tiny motion amplitudes. Those values require actual art evidence; inventing exact coordinates before footprint validation would give workers false certainty. They do not reopen the major decisions above.
