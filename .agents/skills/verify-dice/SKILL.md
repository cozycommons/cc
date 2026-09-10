---
name: verify-dice
description: Launch, health-check, drive, and capture evidence for the Dice mobile web app in the isolated synthetic sandbox. Use for Dice UI or API changes, live referee flows, prediction and pulse, Virtual Dice, browser QA, regression proof, or maintaining the Dice feature map.
---

# Verify Dice

Prove changed behavior through the real mobile interface without using production or disturbing a shared environment.

## Ground the run

1. Read `references/core-principles.md`.
2. Read `features/README.md`, then only the feature recipe relevant to the change.
3. Check `docs/dice-feature-map.md` for release status. For game mechanics, also read `docs/dice-live-event-contract.md`.

## Launch and diagnose

Run from the repository root in Ubuntu WSL.

1. Run `scripts/dice-browser-qa.sh status`.
2. If Supabase is ready and the task owns the free frontend/backend ports, run `scripts/dice-browser-qa.sh start`.
3. If Supabase is absent, note that `scripts/dice-dev.sh setup` resets synthetic data. Run it only when the task explicitly owns that sandbox.
4. For a Codespace, run `scripts/dice-dev.sh status`; obtain the private mobile URL with `scripts/dice-codespace-url.sh <codespace-name>`.

Require Supabase, backend, frontend, and `live_api` to be ready before driving. If browser state becomes surprising, rerun status before changing code.

Never use production. Never reset or stop a shared environment.

## Drive the real journey

- Use a 390x844 mobile viewport; also check about 320px wide when layout changed.
- Prefer visible labels, roles, and text over coordinate clicks.
- Follow the relevant recipe in `features/`.
- Create a uniquely named synthetic game for each run; do not reuse a human or demo game.
- Exercise the actual UI and API path, not test setters or mocks.
- After a mutation, inspect both the visible result and the canonical API/server result where practical.
- Verify behavior contracts, not exact copy, pixels, or card order unless those are the change.

## Preserve evidence

Write evidence beneath `.dice-verification/<UTC timestamp>/<feature>/`. Include:

- commit SHA, viewport, and scenario;
- expected and actual result;
- a screenshot showing the action result;
- relevant status or focused-test output.

Evidence must survive browser cleanup but must not be committed.

## Clean up safely

- Close task-owned tabs and restore any changed viewport.
- Leave uniquely named synthetic games in place unless a scoped delete path exists.
- Run `scripts/dice-browser-qa.sh stop` only if this run started that stack.
- Do not run `scripts/dice-dev.sh stop` unless this run owns the whole Supabase environment.

## Finish

Finish only when focused source checks pass, at least one changed user journey works through the real surface, evidence is preserved, and the feature map still describes the behavior. If the app and map disagree, fix or report the product regression; never edit the map to hide it.

Add a new recipe only for a new user-visible capability. Update an existing recipe when a journey changes. Periodically run every mapped journey against a clean synthetic sandbox.
