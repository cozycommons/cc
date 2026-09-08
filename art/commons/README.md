# Commons room blockout

Open `commons-room-blockout.bbmodel` in Blockbench. This is an editable 3D
proportions-and-style prototype based on
`frontend/public/cozy-commons-room-empty.png`, not a finished sprite pack.

The model contains the room shell plus 15 large prop groups. The prop set covers the orange sofa, rug, coffee and
dining tables, dining chair and bench, floor lamp, record cabinet, olive
loveseat, two plants, kitchen island, bookcase, side table, and storage chest.
The 17 small palette textures are embedded, so no external texture files are
required. Characters deliberately remain expressive 2D sprites rather than
Blockbench models; Phaser composites them over the rendered environment.

The floor spans 128 × 112 model units. Y is up; the back and window walls
are on negative Z and negative X. View from positive X and Z to see the
open interior. Furniture groups have separate pivots for moving/rotating.

`node scripts/commons-room-blockout.mjs` generates the initial geometry.
It refuses to overwrite an existing model unless `--replace-generated` is
passed. Do not use that flag after manual edits unless intentionally
discarding them; the checked-in model is the editable art source.

The current web scene uses `frontend/public/commons/cozy-commons-room-tile-base.png`
as its rendered room shell and `frontend/public/commons/commons-floor-atlas.png`
as a reusable 4 × 4 floor atlas. Phaser lays the atlas down as a 16 × 16
isometric tile layer, then projects all furniture and actor sprites onto that
same grid. The database stores
`tile_x`/`tile_y` as the canonical positions; the older normalized `x`/`y`
values remain only as derived compatibility fields. Large furniture carries a
persisted tile footprint, so moving a sofa or console reserves its full width
and rejects placements that would overlap actors, walls, or other furniture.
The two upper grid edges are also persisted as the room-shell collision layer,
matching the back walls in the rendered room.
Record-console and floor-lamp state changes now receive animated Phaser
feedback, so their persistent state is visible in the room rather than only in
the accessibility controls. Hovering the room also reports the current tile
coordinate and Manhattan distance from the host. Each authoritative one-tile
movement is interpolated between tile centers, so the discrete state still
feels like a walk rather than a teleport. Movable furniture can also be
rotated between south and north orientations; dedicated variants are used
where available and deterministic mirroring fills the remaining silhouettes.
Hovering a reachable destination draws the four-direction tile path the host
would follow; the preview disappears while a command is being committed so
the backend remains the source of truth for the actual movement.
Press `G` to reveal the complete 16 × 16 placement guide, including the
persisted back-wall blockers.

The next art pass should focus on sprite sheets for the people and a small
number of furniture silhouettes. The host, maker, and neighbor walk strips are
now at `frontend/public/commons/assets/host-walk.png`,
`frontend/public/commons/assets/maker-walk.png`, and
`frontend/public/commons/assets/neighbor-walk.png`; Phaser consumes each as
four transparent frames while the actors' tile positions remain
server-authoritative.
Phaser integration and persistent scene state are now connected. No Dice assets
or behavior are changed.
