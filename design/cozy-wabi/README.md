# Cozy Commons — wabi-sabi exploration and common UI

This folder is a self-contained, no-build design direction for Cozy Commons. The landing page keeps the CSS-drawn cottage room as its quiet anchor. [`components.html`](./components.html) is the reusable common UI library: a specimen-first page where the tactile controls and cards arrive before the typography study. [`../index.html`](../index.html) returns to the design-lab index.

The files are intentionally static. Open `index.html` or `components.html` from a static document host. The Dice links point to `/dice`, the real app route; the document preview does not host that route.

## Material tokens

Both pages import [`tokens.css`](./tokens.css), so the room and the component library share the same material vocabulary.

| Token group | Custom properties | Use |
| --- | --- | --- |
| Paper | `--paper`, `--paper-light`, `--paper-deep` | Warm washi surfaces and readable specimens |
| Ink / wood | `--ink`, `--ink-soft`, `--espresso`, `--walnut`, `--walnut-dark` | Text, dark wells, and grounded shadows |
| Glaze | `--moss`, `--moss-dark`, `--clay`, `--clay-light` | Iron glaze green and burnt sienna accents |
| Light | `--amber`, `--butter`, `--blue-dusk` | Local lamp pools, highlights, and the room window |
| Rules | `--line`, `--line-strong`, `--hairline` | Fine imperfect separators and borders |
| Material | `--soft-shadow`, `--paper-shadow`, `--inset-shadow`, `--key-shadow`, `--key-shadow-pressed` | Room, paper, recessed well, and raised-key behavior |
| Shape / type | `--radius-card`, `--radius-small`, `--radius-button`, `--serif`, `--sans`, `--mono` | Asymmetric edges and editorial/ledger roles |
| Interaction | `--focus-ring`, `--ease` | Consistent keyboard focus and short local transitions |

## Common class API

The library uses the `cc-` namespace so it can be lifted into another page without colliding with the room artwork.

| Class | Purpose |
| --- | --- |
| `.cc-navbar`, `.cc-navbar__links`, `.cc-menu-toggle` | Shared responsive navigation; links remain in the document without JavaScript |
| `.cc-display`, `.cc-h1`, `.cc-h2`, `.cc-h3`, `.cc-body`, `.cc-lead`, `.cc-caption`, `.cc-label`, `.cc-mono` | Type roles |
| `.cc-button` + `--primary`, `--secondary`, `--ghost`, `--destructive`, `--icon`, `--small`, `--active`, `--loading` | Raised ceramic-key actions and states |
| `.cc-card` + `--elevated`, `--inset`, `--interactive`, `--project` | Nested paper surfaces with material-specific elevation |
| `.cc-input`, `.cc-select`, `.cc-textarea`, `.cc-choice`, `.cc-switch`, `.cc-range` | Labeled native controls and recessed wells |
| `.cc-segmented`, `.cc-tabs`, `.cc-tabs__panel` | Pill segments and progressive-enhanced tab panels |
| `.cc-badge`, `.cc-avatar`, `progress` | Small status, identity, and completion patterns |
| `.cc-notice` + `--success` / `--error` | Persistent success and error feedback |
| `.cc-accordion` | Native `<details>` disclosure pattern |
| `.cc-dialog`, `.cc-toast` | Native dialog and local toast feedback |

Example button and card markup:

```html
<button class="cc-button cc-button--primary" type="button">save locally</button>

<article class="cc-card cc-card--inset">
  <p class="cc-label">group label</p>
  <h3 class="cc-h3">A quiet well</h3>
  <p class="cc-body">Related details can rest together here.</p>
</article>
```

## Specimen inventory

`components.html` demonstrates the same shared inventory in one place:

- Responsive navbar with landing, library, Dice, and `../index.html` links.
- Display, h1, h2, h3, body, lead, caption, label, and mono type roles.
- Primary, secondary, ghost, destructive, icon, small, disabled, active, and loading buttons.
- Elevated, inset, interactive, and Dice project cards.
- Text, email, search, textarea, native select, checkbox, radio, switch, and range/output controls.
- A locally validated demo beer-die record form with success and error feedback.
- Segmented tabs with visible no-JavaScript fallback panels, arrow/Home/End keyboard navigation, and Enter/Space activation.
- Badges, demo avatars, native progress, success/error notices, native accordion, native dialog, and button-triggered toast.

The room, counts, times, player names, and Dice records are explicitly labeled as demo or sample content. They do not imply live activity.

## Interaction and accessibility notes

- `components.js` only enhances controls after the document is available: it does not need a network request or persistence.
- Tab panels are all present by default; JavaScript marks the tab set as enhanced and then exposes the selected panel.
- The form uses native validity concepts plus local field messages and never submits over the network.
- The dialog closes from its close button, backdrop, or Escape. The toast can be dismissed or times out locally.
- Focus rings are visible, native controls remain recognizable, and interactive targets use a 44px minimum.
- The layout is designed down to 360px and avoids horizontal overflow. `prefers-reduced-motion` removes transitions, spinner motion, and smooth scrolling.
- The room artwork is decorative except for its concise room label and its lamp button. The existing CSS scene remains image-free and portable.
