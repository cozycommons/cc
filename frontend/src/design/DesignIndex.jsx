import React from 'react';
import { Link } from 'react-router-dom';

const DESIGN_SYSTEMS = [
  {
    slug: 'dice',
    name: 'Dice',
    description: 'Warm neutrals, farm-inspired accents, and the component language for Dice.',
  },
];

export default function DesignIndex() {
  return (
    <main className="min-h-screen bg-theme-background text-theme-foreground">
      <div className="mx-auto max-w-5xl px-6 py-16 sm:px-8 sm:py-24">
        <header className="max-w-2xl">
          <Link className="text-sm font-medium text-muted-foreground hover:underline" to="/">
            Cozy Commons
          </Link>
          <p className="mt-12 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Design systems
          </p>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-6xl">
            A home for the visual languages we use.
          </h1>
          <p className="mt-6 text-lg leading-8 text-muted-foreground">
            Each system has its own tokens, components, and living reference page.
          </p>
        </header>

        <section className="mt-16" aria-labelledby="available-design-systems">
          <h2 id="available-design-systems" className="sr-only">Available design systems</h2>
          <div className="grid gap-5 sm:grid-cols-2">
            {DESIGN_SYSTEMS.map((system, index) => (
              <Link
                key={system.slug}
                className="group rounded-2xl border border-theme-border bg-theme-card p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
                to={`/design/${system.slug}`}
              >
                <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  <span>DS-{String(index + 1).padStart(2, '0')}</span>
                  <span aria-hidden="true" className="text-lg transition-transform group-hover:translate-x-1">→</span>
                </div>
                <h3 className="mt-12 text-3xl font-semibold tracking-tight">{system.name}</h3>
                <p className="mt-3 max-w-sm leading-7 text-muted-foreground">{system.description}</p>
                <span className="mt-8 inline-flex text-sm font-semibold">Open {system.name} design system</span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
