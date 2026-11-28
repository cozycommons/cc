# Cozy Commons design system

The React component library lives at `/design`. It uses the Radix Nova
registry from shadcn/ui and the Cozy Wabi theme in
`frontend/src/design/commons-theme.css`. The theme maps the original paper,
moss, clay, and ink materials onto shadcn's semantic roles with light and dark
palettes. It also carries over Wabi's serif headings, sans-serif controls,
asymmetric corners, recessed fields, and raised buttons.
The gallery includes interactive examples for actions, forms, data, feedback,
and overlays.

## Use the system

- Import components from `frontend/src/components/ui/` using the existing
  `@/components/ui/` aliases. Start with the shared component variants and
  semantic tokens, then compose application-specific layouts.
- Import `frontend/src/design/commons-theme.css` from the themed entry point
  and apply `commons-theme` to the document element for the lifetime of the
  surface so dialogs, menus, and toasts inherit its tokens when portaled.
  Use `design/cozy-wabi/tokens.css` for the source material tokens.
- Run `npx shadcn@latest info --json` from `frontend/` before adding a new
  component. The Vite app uses Tailwind CSS v4, Radix, and Lucide.
- Keep gallery-only utilities in `frontend/src/design/design-utilities.css`.
  Verify the initial route bundle budget with `npm run build:check`.
- Follow the installed shadcn, UI SDK, and Web Design Guidelines skills.
  The Commons primitives use shadcn and Radix. Apply the SDK's keyboard,
  focus, and naming guidance to component composition.

```sh
npm run dev --prefix frontend
```

Open `/design` in the development frontend. The examples use local sample data.

The original Wabi specimens and the Clay and Skeuo explorations remain in
their respective directories. The Commons homepage also uses the Wabi materials.
