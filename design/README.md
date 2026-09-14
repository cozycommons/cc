# Cozy Commons design lab

Three standalone landing-page explorations for the Cozy Commons home page:

- `cozy-wabi/` — quiet imperfection, fiber/paper, asymmetry, and soft pools of light.
- `cozy-clay/` — rounded clay surfaces, tactile bevels, and warm playful volume.
- `cozy-skeuo/` — a crafted cottage shelf with wood, linen, brass, and physical controls.

## Preview

Open `design/index.html` in a browser for the comparison board, or serve the
directory locally if your browser restricts local iframe loading:

```sh
cd design
python3 -m http.server 4173 --bind 127.0.0.1
```

Then open <http://127.0.0.1:4173/>.

The production React app is intentionally not changed by these explorations.
Each direction owns its HTML/CSS/JS and includes a short token rationale so
the strongest parts can be combined later into a real Cozy Commons system.

## Component libraries

Each direction includes `components.html`, `components.css`, and `components.js`.
Open the library from the comparison board or the landing page. The board can
switch between landing-page and component-library previews.

All three cover navigation, typography, buttons, cards, text fields, search,
textarea, select, checkbox, radio, switches, sliders, segmented controls, tabs,
badges, avatars, progress, notices, accordions, dialogs, and toasts. Demonstrations
run locally; sample forms do not send data. Each variant's README documents its
class names and tokens for reuse. These are HTML/CSS/JavaScript libraries, not
yet React component packages.

The Dice links retain `/dice` for eventual app integration. The standalone static
preview server does not host that app route. Room activity and sample records
are illustrative, not connected to live data.
