# Product specification: a room that quietly lives

Status: selected product direction; implementation is in progress. Major decisions and rationale are in [DIRECTION](DIRECTION.md). Read [README](README.md) for strategy and [TECH](TECH.md) for implementation contracts.

## Experience

The visitor opens Cozy Commons and finds a warmly lit little room already going about its evening. A resident shifts their weight while reading; another takes a few slow steps toward the window. Lamplight rests on the rug. A leaf moves almost imperceptibly. The page is a place to leave open while doing something else, and still a clear entrance to Dice.

The existing illustrated room has appealing amber light, dark wood, upholstered furniture, plants, and domestic detail. Preserve that emotional identity. Replace the appearance of individually pasted cutouts with a coherent, grounded miniature world. Detail should come from deliberate silhouettes, material clusters, facial features, folds, books, and small domestic objects; avoid adding noise or constant movement.

## Scope and priority

Release requirements: coherent art, grounded placement, correct overlap, reusable four-view characters, three distinct residents and their authored routines, material/light polish, backend-owned world definitions, accessible passive presentation, resilient loading and measured performance. These ship together; a partial technical demo is not the release.
Deferred: visitor-controlled movement, furniture editing, multiplayer presence, chat, inventory, economy, weather system, audio, live day/night simulation, procedural room generation, and a full character editor. Existing command endpoints remain, but public ambient mode does not invoke them.

This is an intentional shift from an interactive demo to an ambient homepage. There is no public walking instruction, version counter, hover path, tile label, selection outline, draggable furniture, global WASD handler, or scene control card. Preserve `/dice` navigation and all Dice behavior. Diagnostics belong in development tooling. The room itself remains the interface; project links are the only public actions.

## Art direction

Selected theme: **The evening common room**. Original, warm, expressive pixel art with the readable silhouettes and friendly scale associated with Stardew and Pokémon, with more intentional material and character detail. Do not reproduce their characters, sprites, locations, or UI.

- Use a fixed orthographic isometric camera matching the world grid. All furniture bases, floor patterns, rug edges, and architectural lines follow that projection.
- The palette starts with espresso/plum shadows (`#251B27`), walnut (`#674331`), amber (`#E2AB65`), cream (`#F1DCB5`), moss (`#697451`), rust upholstery (`#B86D43`), and muted blue (`#63788B`). These are art direction anchors, not a global seven-color restriction. Keep local materials within small, coherent color ramps.
- Light comes primarily from warm interior lamps; windows introduce quieter cool tones. No white bloom fringe around cutouts, black drop shadows pasted behind every object, or conflicting baked highlight directions.
- Use a consistent source pixel density: three source pixels per logical scene unit. Final room art is authored against a 1536×1536 template corresponding to the 512×512 world view; a tile is 96×60 source pixels. Preserve hard, intentional pixel clusters. The responsive page can downsample uniformly; no independent item scaling or frame-to-frame sampling changes.
- Adult residents are approximately 60–70 logical units tall, with expressive heads roughly one quarter to one third of height. Feet and hands remain legible at the actual desktop display size. Sofa backs are around 30–42 units above the floor; seated proportions are checked against the same mannequin. The art slice must fit these proportion ranges while retaining the fixed rig bounds; changes outside the ranges belong to the integrating lead.
- Favor three detail scales: clear room silhouette, readable furniture/person silhouettes, sparse close-up discoveries. Use low-contrast floor variation; avoid the live scene’s checkerboard-like patchwork. Leave 25–35% of walkable floor visibly open. Avoid a showroom of evenly spaced furniture or a blanket of clutter.

## Room composition

Use the current 16×16 logical grid and an open front cutaway. Retain the kitchen/windows at the rear, but rebuild their render layers to match actual geometry. The live grid-overlay review shows that the present logical floor domain and painted shell boundary do not coincide. Acceptance requires all four projected grid-domain corners and the intended room floor boundary to match the same template. The original furnished illustration is a mood reference; the current tile-base image is evidence of the existing shell. Neither is a final spatial template.

Arrange three connected zones:

| Zone | Approximate logical region, before footprint fitting | Visual purpose |
| --- | --- | --- |
| Listening nook | u=2–6, v=4–9 | Rust sofa, woven rug, low table, record cabinet, small lamp; primary focal cluster |
| Shared table | u=6–10, v=8–12 | Walnut table, two chairs, one mug/book composition; maker's resting area |
| Window/green corner | u=10–14, v=2–7 | Olive seating, one tall plant, secondary lamp; quieter counterweight |

These regions are design envelopes, not final seed coordinates. The layout worker must produce exact entity placements and prove their occupancy before seeding them. Keep at least one two-cell-wide connected circulation spine and one-cell clearance around the full ambient route. Avoid squeezing the route between overlapping art silhouettes even where collision permits it. Windows, light pools, and open floor should guide the eye toward the room center; the Dice link remains readable outside the scene.

The new layout omits the red armchair and bar stool to open circulation; legacy data remains supported. The table gets two distinct chair instances. Maintain the listening nook as the primary focus and avoid placing its sofa against the kitchen work surface. See DIRECTION for the intended silhouette hierarchy.

Three residents retain stable identities: host (ochre jacket), maker (muted blue workwear), neighbor (moss/rust accents). Give each a distinctive hair silhouette and outfit. Additional combinations should feel like new people from the same world, not recolors of the same flattened illustration.

## Grounding and overlap requirements

G1. Each asset has an authored ground anchor independent of transparent padding. A person's standing foot root, a lamp pedestal, a pot base, and a rug's tile center connect to their declared floor position at every size and animation frame.

G2. Furniture support points align with its projected footprint. Multiple legs may contact different points; they must not all be forced onto one tile center. Shadows originate at these supports and do not conceal gaps.

G3. Rugs are flat floor decorations. People, shoes, legs, furniture, and contact shadows always draw above them, including at the rug's near edge. Rug patterns and borders agree with the floor perspective; rugs are not obstacles.

G4. A person walking behind a sofa is hidden by its body/back where appropriate; the same person walking in front is visible. A plant canopy may hide the upper body while the pot obeys the correct ground order. Multi-tile tables and sofas must pass side and corner traversal, not just a single front/back test.

G5. Identical positions render identically after reload. Crossing a depth boundary does not flicker, reverse order on equal depths, or depend on entity insertion order. Shadows, accessories, carried items, and light effects follow their owner’s intended depth.

## Characters and motion

C1. Every resident supports four distinct view families: front-right, front-left, back-left, back-right, mapped to logical world directions in TECH. This fulfills front/back/left/right in this isometric world. Back views show the back of the head and outfit; horizontal flipping cannot synthesize a back view.

C2. A character is assembled from compatible body/skin, eyes, hair, outfit, footwear, and optional accessory parts. Shared frame registration and direction-specific part order prevent seams. Include a reference kit and three complete residents; demonstrate at least twelve valid combinations without per-character renderer changes.

C3. Each direction has an eight-frame walk cycle, subtle idle breathing, and blink expressions where eyes are visible. Idle breathing takes 4–7 seconds, shifts chest/head by at most 0.6 logical units, and leaves feet planted. Blinks occur roughly every 3.5–8 seconds and last 120–180ms. Different people must not blink or breathe in sync. These timing ranges are tunable initial targets.

C4. Walking takes 0.8–1.2 seconds per adjacent tile, with a gait calibrated to stride length. Avoid easing to a full stop at each intermediate tile. Turn at corners; do not slide sideways or moonwalk. Use a short start/stop transition and recover to a planted pose.

A1. Rest dominates the scene: each resident remains at rest at least 75% of a three-minute authored cycle. The initial cycle permits only one walking resident at a time. The shipping score follows DIRECTION: one resident outing in each successive 60-second window, at most 20 seconds walking per resident per cycle, and at least 10 seconds still at each window boundary. Distinct resting views/postures and one reusable subtle glance gesture are required. Sitting and page-turn systems are deferred.

A2. Warm light remains steady in this release; there is no lamp/candle intensity animation. Do not pulse exposure over the entire scene. Plant motion is confined to one leaf cluster, about 0.3–0.8 degrees over 7–12 seconds. Steam can appear from one state-backed hot object, with at most three wisps lasting 4–8 seconds. Music-note icons and floating notification-like symbols are removed.

A3. At any moment, at most one large movement (walking), two medium gestures, and a few local micro-motions should attract attention. Do not add particles until the unanimated composition passes visual review. The room must already look good at rest.

## Backend meaning

B1. Refreshing the page preserves the same room, object states, resident identities and appearances, and ambient program. Clients derive the same scheduled pose from the same version and server time. They need not share decorative blink phases exactly, but their residents must not roam independently through different furniture.

B2. World state stores the scene and its schedule, not every animation frame. The backend validates placement and route safety. Public ambient browsing causes zero command writes. Lighting and record-player appearances reflect actual object state.

B3. On first-load failure, show a designed static fallback of this room and concise connection status; do not invent a live shared room or fabricate residents. On later failures, retain the last validated state and stop locomotion at a safe standing point after the cached schedule freshness limit. Recovery reconciles through the transition policy in TECH.

## Homepage, accessibility, and operating targets

- The scene is the dominant visual, with warm neutral page chrome. Keep a compact wordmark and clear project shelf. Reserve the scene's square before load to prevent layout shift. At 1440×900, target a 620–760px scene; at 390×844, use the available width with 16px side margins, a project shelf below with 24–40px spacing from the scene’s content box, no sideways scrolling, and no cropped scene content. Do not reserve a tall empty region between the scene and project link.
- Do not capture scrolling, pinch zoom, arrow keys, WASD, or context menus in ambient mode. The canvas itself is not a tab stop. Provide a short semantic description, e.g. “A warmly lit common room with three residents, plants, and a listening nook.” Do not expose every prop as a button.
- Ambient browsing has no public pause or room-status control. Reduced motion starts with static safe home poses, removes motion-based loading/recovery transitions, and responds immediately to system preference changes. Project links remain usable. The renderer may retain an internal paused policy for development fixtures or future embeddings; reduced motion always prohibits animation.
- On hidden tabs, stop animation work and polling; refresh and reconcile on return. Do not replay missed walks at high speed.
- Release budgets: initial compressed scene assets ≤8MB, decoded texture residency ≤64MiB, ≤250 draw calls, and one renderer instance. On recorded reference hardware at 1440×900, target p95 frame time ≤20ms during a 60-second visible run; at mobile 390×844 target ≤33ms. Record hardware, browser, DPR, and quality tier. These targets require actual measurement before acceptance, not a claim based on desktop intuition.
- Cap rendering DPR at 2. Prefer baked character composites, pooled particles, and fewer effects before reducing essential art fidelity. Use a static fallback for renderer failure or unsupported graphics; preserve navigation.

## Product acceptance

A release must show: (1) a beautiful resting full room, (2) contact overlays proving every orientation/frame is grounded, (3) continuous front/back/side/corner crossings with correct occlusion, (4) rug-edge traversal, (5) twelve character combinations and all view families, (6) a three-minute ambient recording with long rests, (7) two-client/reload state consistency, (8) reduced motion across all effects, (9) loading/offline/recovery and mobile navigation, and (10) measured performance plus a ten-minute unattended visual review. Geometry and API tests supplement these visual proofs; they cannot replace them. See PLAN for exact fixtures and worker ownership.
