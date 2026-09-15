# Cozy Commons design system

Cozy Wabi is the chosen visual direction for Cozy Commons. Its warm washi
paper, iron glaze, editorial serif, and ledger-like labels now power the React
home page at `/` and the living component library at `/design`.

The `cozy-wabi/` folder remains the source reference for the shared tokens and
CSS artwork. The Clay and Skeuo folders are retained as historical explorations;
the comparison board is no longer part of the deployed app.

## Preview

To inspect the original static Wabi reference locally:

```sh
cd design/cozy-wabi
python3 -m http.server 4173 --bind 127.0.0.1
```

Then open <http://127.0.0.1:4173/index.html>. The production React app imports
the Wabi styles directly and adds the local interactions in React.

## Component libraries

The Wabi direction includes `components.html`, `components.css`, and
`components.js` as a static reference alongside the production React library.

The Wabi reference covers navigation, typography, buttons, cards, text fields,
search, textarea, select, checkbox, radio, switches, sliders, segmented
controls, tabs, badges, avatars, progress, notices, accordions, dialogs, and
toasts. Demonstrations run locally; sample forms do not send data. Its README
documents the class names and tokens that the React pages reuse.

The Dice links retain `/dice` for eventual app integration. The standalone static
preview server does not host that app route. Room activity and sample records
are illustrative, not connected to live data.
