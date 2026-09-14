# Cozy Commons — skeuo room + common UI library

This standalone direction is a dim walnut cottage workshop for Cozy Commons. The landing room is still a CSS-built scene: wall, window, shelf, lamp, desk, drawer, paper, ink bottle, dice, and mug are preserved in `styles.css` and the ambient-light animation remains in `script.js`.

The reusable reference is `components.html`. It is intentionally a compact, dense workbench rather than a second marketing page. `components.css` and `components.js` have no dependencies and work from a static file server or a direct file open.

## Open the direction

- [Landing room](./index.html) — the preserved cottage scene and Dice project shelf.
- [Common UI library](./components.html) — the reusable component inventory and local demonstrations.
- [Design lab](../index.html) — the three-direction comparison board.
- Dice remains a link to `/dice`; this static design document does not host that route.

## Material tokens

Both CSS files expose the same `--cc-*` token names and values so the library can be moved into another static shell without translating the material language.

| Token | Value / use |
| --- | --- |
| `--cc-ink`, `--cc-ink-soft` | `#201711`, `#3d2c20`; ink on paper and readable dark text |
| `--cc-walnut`, `--cc-walnut-deep` | `#4b2b1c`, `#382318`; room frame, wood, and hard edges |
| `--cc-terracotta` | `#a85f3d`; warm project and error accents |
| `--cc-paper`, `--cc-paper-light` | `#ead8b8`, `#f6e9cf`; ledger surfaces and cream type |
| `--cc-linen` | `#c8b795`; muted secondary type |
| `--cc-moss`, `--cc-moss-deep` | `#586442`, `#28352a`; stitched green surfaces and success states |
| `--cc-brass`, `--cc-brass-light` | `#c2934a`, `#efca7c`; highlights, actions, focus, and status lamps |
| `--cc-focus`, `--cc-success`, `--cc-error`, `--cc-warning` | `#ffe1a2`, `#a9cf8c`, `#f0a082`, `#e7bd72`; accessible state accents |
| `--cc-radius-sm/md/lg` | `5px`, `12px`, `22px`; restrained physical corners |
| `--cc-shadow`, `--cc-deep-shadow` | Layered contact and room shadows |
| `--cc-font-display` | Georgia / Times-style book typography |
| `--cc-font-ui` | Trebuchet MS / Arial for functional labels |
| `--cc-font-mono` | System mono for tokens, values, and compact metadata |
| `--cc-ease` | `cubic-bezier(0.22, 0.61, 0.36, 1)` for small physical transitions |

The CSS-generated grain is an inline data texture, not an external image. No asset pipeline or network-loaded font is required.

## Class API

All reusable names use the `cc-` prefix. Add the base class first, then a material or state modifier where needed.

| Family | Classes |
| --- | --- |
| Page / nav | `.cc-body`, `.cc-library`, `.cc-navbar`, `.cc-navbar__brand`, `.cc-navbar__links`, `.cc-navbar__link`, `.cc-navbar__menu` |
| Type | `.cc-type-display`, `.cc-type-h1`, `.cc-type-h2`, `.cc-type-h3`, `.cc-type-body`, `.cc-type-lead`, `.cc-type-caption`, `.cc-type-label`, `.cc-type-mono` |
| Buttons | `.cc-button`, `.cc-button--primary`, `--secondary`, `--ghost`, `--destructive`, `--icon`, `--small`, `.is-active`, `.is-loading`, `.is-disabled` |
| Cards | `.cc-card`, `.cc-card--elevated`, `.cc-card--inset`, `.cc-card--interactive`, `.cc-card--project` |
| Fields | `.cc-field`, `.cc-input`, `.cc-textarea`, `.cc-select`, `.cc-choice`, `.cc-switch`, `.cc-range`, `.cc-range-readout`, `.is-error` |
| Selectors | `.cc-segmented`, `.cc-segment`, `.cc-tabs`, `.cc-tabs__list`, `.cc-tab`, `.cc-tab-panel` |
| Feedback | `.cc-badge`, `.cc-badge--success`, `.cc-badge--error`, `.cc-badge--quiet`, `.cc-avatar`, `.cc-progress`, `.cc-notice`, `.cc-notice--success`, `.cc-notice--error` |
| Disclosure | `.cc-accordion`, `.cc-accordion__item`, `.cc-accordion__summary`, `.cc-dialog`, `.cc-toast` |

### Basic usage

```html
<link rel="stylesheet" href="./components.css" />

<button class="cc-button cc-button--primary" type="button">
  save locally
</button>

<article class="cc-card cc-card--elevated cc-card--interactive">
  <p class="cc-card__eyebrow">project card</p>
  <h2 class="cc-card__title">Dice</h2>
  <p class="cc-card__copy">Beer die records and stats.</p>
</article>
```

For controls, keep native elements and add the class: `<input class="cc-input">`, `<textarea class="cc-textarea">`, `<select class="cc-select">`, `<progress class="cc-progress">`, and `<details class="cc-accordion__item" open>`. Use real `<label for>` pairs, fieldset legends for grouped choices, and an accessible name for icon-only buttons and switches.

`components.js` activates elements marked with these data hooks:

- `data-demo-switch` toggles `aria-pressed` and its visible on/off label.
- `data-range-output="output-id"` keeps a native range and `<output>` synchronized.
- `data-segment` / `data-segment-output` updates the segmented-selector readout.
- `data-tabs`, `data-tab-target`, and `data-tab-panel` provide click and Arrow/Home/End keyboard tab behavior.
- `data-component-search` updates local search feedback only.
- `data-demo-form` validates with native constraints, prevents submission, and confirms locally.
- `data-dialog-open`, `data-dialog`, and `method="dialog"` provide a native dialog with close-button and Escape paths.
- `data-toast-trigger`, `data-toast`, and `data-toast-dismiss` show and dismiss a local toast.

## Specimen inventory

`components.html` contains the complete reference shelf:

1. Responsive navbar with native disclosure menu, landing link, library link, and `../index.html` design-lab link.
2. Display, H1, H2, H3, body, lead, caption, label, and mono type samples.
3. Primary, secondary, ghost, destructive, icon, small, disabled, loading, and active button states.
4. Elevated, inset, interactive, and project cards, including Dice beer die records and demo stats.
5. Text, email, search, textarea, native select, checkbox, radio, switch, and range/output controls.
6. Segmented selector and tabs with visible local panel updates and keyboard navigation.
7. Badges, avatar, native progress, success notice, and error notice.
8. Native accordion, native dialog with close/Escape, and button-triggered toast.
9. A local-only demo form with required fields, an explicit error specimen, and confirmation feedback.

Hover, focus-visible, active/pressed, disabled, loading, and error treatments are defined in CSS. Targets are at least 44px where a person taps or keys. Reduced-motion and forced-colors rules are included, and the accordion opens by default so its copy is not dependent on JavaScript.

## Static review

Open either HTML file directly, or serve only this folder with any static server. No server is required for implementation review. The documented repository workflows remain outside this design-only directory; no production app, `/dice` deployment, database, or external service is changed here.
