# Cozy Room Tile Scene

## Summary

Replace the current painted/isometric Commons scene with a playable, cozy indoor room rendered as a pixel-art tile world. The room should feel like a small farming-sim interior: orthographic top-down perspective, four-direction residents, deliberate furniture placement, readable walkable space, and collision that makes the room behave like a game rather than a decorative illustration.

The public home remains the Cozy Commons landing page and the Dice project link remains available, but the room itself becomes the primary interactive surface.

## Figma

Figma: none provided.

## Goals

- Make the room legible as a grid of floor, wall, trim, doorway, and furniture tiles.
- Give the visitor a small, satisfying movement loop without introducing a separate game mode or changing `/dice`.
- Replace the current scene art with a cohesive warm pixel-art interior and new resident/object sprite treatment.
- Preserve shared-scene persistence, safe placement, and the existing API envelope.

## Non-goals

- Reproducing Stardew Valley's proprietary art, characters, names, UI, or exact room layouts.
- Building farming, inventory, crafting, combat, dialogue, or multiplayer simulation systems.
- Replacing the Dice application or changing its routes.

## Behavior

1. The `/` route opens on a single cozy indoor room. The room is presented in a flat orthographic top-down view: columns run left-to-right, rows run top-to-bottom, and every floor position has the same square tile size. The room does not use an isometric diamond projection, perspective camera, or painted full-room composition as the primary world representation.

2. The visible room contains an authored shell with floor tiles, perimeter walls, a readable doorway, a warm window/light source, and open floor space. The default composition includes a bed, work table, chair, bookcase, fireplace, rug, chest, and plant arranged around clear paths. The shell and furniture should read as a single cozy room, not as a debug grid.

3. The room uses a stable 16×16 logical tile grid. Tiles are the source of truth for placement and movement; normalized coordinates are compatibility data only. The camera fits the whole room on desktop and on small screens without stretching sprites non-uniformly. Pixel edges remain crisp.

4. The visitor can move the host resident one tile at a time with Arrow keys or WASD. Each accepted step moves exactly one cardinal tile, updates the host's facing direction, and uses the appropriate front/back/left/right sprite view. Diagonal movement is not accepted.

5. Clicking or tapping a reachable floor tile asks the host to walk there through the shortest available cardinal path. The host advances one tile at a time, stops before blocked or occupied cells, and never cuts through furniture, walls, the room boundary, or another resident. A target marker may appear briefly on the selected tile.

6. Movement feels continuous at the tile boundary: the host's feet stay anchored to the ground, walking animation follows distance traveled, and arrival settles into a planted idle pose. The room does not teleport the host between non-adjacent tiles or slide the sprite independently of its tile route.

7. Furniture occupies an authored footprint, not merely the tile under its visual center. A placement is valid only when every footprint cell is inside the room and free of shell blockers, blocking furniture, and residents. Rugs and other explicitly decorative objects can overlap walkable floor without blocking it.

8. Movable furniture can be selected and dragged to another tile in the room. While dragging, the full footprint is previewed; valid placement is shown as an affirmative highlight and invalid placement as a warning highlight. Releasing on an invalid tile returns the object to its original position and does not change shared state. Rotation, when offered by an object's catalog entry, changes its orientation without changing its identity and re-checks the footprint.

9. Scene changes are shared and authoritative. A successful movement or placement is submitted through the existing Commons command API and the returned canonical scene becomes the basis for subsequent local interaction. Concurrent edits, stale versions, rejected commands, and failed requests leave the last valid room visible and provide a quiet, non-blocking status message; they must not apply a locally invented layout over the server state.

10. The three existing residents remain visible when present in the canonical scene. Non-player residents use the same four-direction sprite language and stand on valid tiles. Existing ambient schedules may position them when valid, but a direct user command that changes blocking geometry or a resident's home position disables the affected ambient schedule according to the existing scene rules.

11. Objects with semantic state retain visible but restrained feedback: an active fireplace/light glows, an inactive one is dimmer, and purely decorative objects do not invent new state. Effects remain attached to their source tile, render behind residents when appropriate, and never create collision by themselves.

12. Rendering order follows tile rows: floor and floor decorations are beneath entities; entities with a lower ground row render behind entities with a higher ground row; equal-row ties are deterministic. Tall furniture may extend upward visually while its blocking/support cells remain at its authored base. Residents must be able to pass in front of and behind furniture without the whole sprite popping to a fixed global layer.

13. The default scene has a clear loading state, retains the last valid snapshot during a short API outage, and becomes visually still after the existing freshness threshold rather than implying that stale residents or effects are current. Returning to a visible tab requests a fresh scene before resuming movement. Reduced-motion users see planted sprites and static semantic effects without idle bobbing, blinking, or route animation.

14. If the Phaser renderer cannot load, the page still exposes an accessible room description and a static room fallback. The description includes the number of residents and placed objects and identifies the surface as a top-down tile-based Cozy Commons room. The canvas has an accessible name, and movement/status affordances do not rely on color alone.

15. Keyboard focus remains usable around the room. The scene does not steal focus from the page, but a focused game surface can receive movement keys, and Escape cancels an in-progress furniture drag/path preview. Touch users can tap to walk and drag movable furniture without browser scrolling inside the room frame.

16. The existing Cozy Commons wordmark, project shelf, and `/dice` link remain usable around the room. The rewrite must not change Dice application routes, Dice data behavior, scene API paths, or the old `jasonkeung.com/dice` deployment.

17. The room uses original/re-authored pixel-art assets with no Stardew Valley names, logos, copied sprites, or other proprietary game assets. Asset failures are isolated: a missing optional prop does not prevent the shell and residents from rendering, while an invalid canonical snapshot is rejected as a whole.
