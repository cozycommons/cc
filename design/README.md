# Cozy Commons design system

The React component library lives at `/design`. It uses the Radix Nova
registry from shadcn/ui and the Commons theme in `frontend/src/index.css`.
The theme uses Geist, semantic color tokens, and the system color preference.
The gallery includes interactive examples for actions, forms, data, feedback,
and overlays.

## Use the system

- Import components from `frontend/src/components/ui/` using the existing
  `@/components/ui/` aliases. Start with the shared component variants and
  semantic tokens, then compose application-specific layouts.
- Apply `commons-theme` to the document element for the lifetime of a themed
  surface so dialogs, menus, and toasts inherit its tokens when portaled.
  Import `@fontsource-variable/geist` in the themed entry point.
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

The archived Wabi, Clay, and Skeuo references remain under their original
directories. The Wabi materials are also used by the Commons homepage.
