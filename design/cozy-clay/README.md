# Cozy Clay landing page and component library

Self-contained Cozy Commons landing-page exploration for the claymorphism direction.

Open `components.html` for the matching reusable UI library. It extends the
landing page's baked-clay, moss, oat, and charcoal tokens into a dense tactile
tray of buttons, cards, fields, selectors, feedback, and overlays.

Open `index.html` directly, or serve this directory with any static file server. It has no external runtime dependencies, fonts, or images. The room, dice illustration, plant, and decorative texture are all made with CSS and inline SVG.

## Design tokens

| Token | Value / intent |
| --- | --- |
| Baked clay | `#B75F41` primary action, active state, and warm focal light |
| Clay highlight | `#D88662` soft edge highlight and selection color |
| Moss | `#687350` secondary action, status, and grounded natural accent |
| Oat | `#F6F0E7` page ground; `#EBE1D2` panels and quiet surfaces |
| Charcoal | `#29251F` readable ink with warm undertone |
| Type | Rounded system stack for UI; Georgia serif italic for the human / handmade contrast |
| Radii | `42px` hero object, `30px` cards, `20px` controls, `14px` small details |
| Elevation | Layered warm shadows plus light inset edges; pressed controls switch to inset-only shadows |
| Motion | Slow lamp/core/die breathing, tiny hover lift, and scroll-in reveals. No animation is required to understand the content. |

## Accessibility intent

The page uses semantic sections, a skip link, visible keyboard focus rings, descriptive labels for CSS artwork, and a `prefers-reduced-motion` mode that removes ambient motion and reveal transitions. Status uses text plus color, and all primary actions remain readable at mobile widths. The time label is a local, non-essential enhancement; if scripting is unavailable, the static time is still meaningful.

## Reusable component API

The library exposes named `clay-*` classes for buttons, cards, fields, badges,
avatars, progress, notices, segmented controls, tabs, accordions, dialogs, and
toasts. The type roles are `type-display`, `type-h1`, `type-h2`, `type-h3`,
`type-body`, `type-lead`, `type-caption`, `type-label`, and `type-mono`.

`components.js` progressively enhances the mobile menu, range outputs,
segmented controls, keyboard tabs, local form validation, dialog, and toast.
The demo form never submits data or performs a network request.

The component page includes primary, secondary, ghost, destructive, icon,
small, active, disabled, and loading button specimens; elevated, inset,
interactive, and project cards; text, email, search, textarea, select,
checkbox, radio, switch, and range controls; feedback and overlay patterns.
All sample records and room activity are labeled as illustrative data.
