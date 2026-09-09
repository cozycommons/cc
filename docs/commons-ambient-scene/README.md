# Commons ambient scene — specification and execution guide

Status: direction selected; specifications only. No implementation is authorized by this document.
Inspected baseline: `83c9bafe2759cef0728a1446245fe2e46bead56c` (2026-09-08).

## Strategy

Make the home page feel like looking into a small, inhabited evening room: warm pools of lamplight, tactile furniture, expressive people, long pauses, and occasional unhurried movement. Preserve the warmth of the existing room while replacing inconsistent spatial and animation assumptions. The scene should reward a minute of watching without demanding a click.

1. Establish a shared spatial contract: tile centers, continuous ground positions, explicit sprite contact points, footprints, and occlusion geometry.
2. Prove that contract with a small vertical slice: one rug, one sofa, one plant, and one four-view actor walking in front and behind them.
3. Bring the room shell, floor, furniture, shadows, and light into one coherent art pipeline. Redesign assets that cannot satisfy the contract.
4. Build characters from compatible authored parts, export selected recipes at build time, and render true front/back/left/right views, walking, breathing, blinking and a restrained glance.
5. Describe ambient activity in versioned backend state; render time continuously on the client without writing animation frames to the database.
6. Compose the complete room, simplify homepage chrome, and validate grounding, depth, motion, accessibility, performance, and recovery.

## Documents

- [DIRECTION.md](DIRECTION.md): selected product and architecture decisions, their rationale, and lead/worker authority. Read this first.

- [PRODUCT.md](PRODUCT.md): experience, art direction, scope, and acceptance criteria.
- [TECH.md](TECH.md): normative world, asset, character, state, and rendering contracts.
- [PLAN.md](PLAN.md): bounded worker tasks, dependencies, handoff requirements, and release gates.
- [AUDIT.md](AUDIT.md): current-state evidence, limitations, and requirement coverage.

DIRECTION sets the major decisions; PRODUCT, TECH and PLAN express their behavior, contracts and execution. Numeric values explicitly marked as calibration ranges are art targets; invariants and schemas in TECH are contracts. Changing a contract requires updating its consumers and fixtures together. Workers must implement only their assigned task after implementation is separately requested.

## Decisions

- Keep React for page chrome and Phaser for rendering; no engine rewrite or live 3D runtime.
- Keep the 16×16 logical room and the current 32×20 projected tile ratio for the first release; replace the artwork to match the grid, rather than distorting the grid to match independent images.
- Use a coherent high-resolution pixel-art treatment with original characters. Stardew/Pokémon are mood references, not assets to copy.
- Ambient mode is the public default. Existing mutation APIs remain available for later interaction; editing is outside this visual release.
- Backend state owns layout, appearances, semantic light states, and ambient schedules. Client time evaluation owns interpolated poses and decorative motion.
- No database changes, artwork replacement, runtime changes, installation, deployment, or production access occur during this planning task.
