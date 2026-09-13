import React from 'react';
import { IconButton } from '../components/core/IconButton';
import { SunIcon, MoonIcon, SparkleIcon } from '../components/decor/icons';

const THEME_META = {
  light: { next: 'dark', icon: MoonIcon, label: 'Switch to dark mode' },
  dark: { next: 'jaycee', icon: SparkleIcon, label: 'Switch to Jaycee mode' },
  jaycee: { next: 'light', icon: SunIcon, label: 'Switch to light mode' },
};

const LINKS = [
  { href: '#foundations', label: 'Foundations' },
  { href: '#components', label: 'Components' },
  { href: '#prototypes', label: 'Prototypes' },
  { href: '#art', label: 'Art' },
];

export function DesignNav({ theme, onToggleTheme }) {
  const [scrolled, setScrolled] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const scrolledBg = theme === 'dark'
    ? 'rgba(2,2,10,0.82)'
    : theme === 'jaycee'
      ? 'rgba(252,238,246,0.86)'
      : 'rgba(247,241,230,0.86)';

  const themeMeta = THEME_META[theme] || THEME_META.light;
  const ThemeIcon = themeMeta.icon;

  return (
    <div
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        background: scrolled ? scrolledBg : 'transparent',
        backdropFilter: scrolled ? 'blur(10px)' : 'none',
        borderBottom: scrolled ? '1px solid var(--border-subtle)' : '1px solid transparent',
        transition: 'background var(--duration-base) var(--ease-standard), border-color var(--duration-base) var(--ease-standard)',
      }}
    >
      <div
        style={{
          maxWidth: 'var(--content-max-width)',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '18px var(--gutter)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <a
            href="/"
            style={{
              fontFamily: 'var(--font-display)',
              textTransform: 'uppercase',
              fontSize: '19px',
              letterSpacing: 'var(--tracking-display-xs)',
              color: 'var(--text-primary)',
            }}
          >
            Jason Keung
          </a>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: 'var(--tracking-label)',
              color: 'var(--accent-moss)',
              border: '1px solid var(--accent-moss)',
              borderRadius: 'var(--radius-pill)',
              padding: '2px 8px',
            }}
          >
            Design System
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '22px' }}>
          <div className="ds-nav-links" style={{ display: 'flex', gap: '26px' }}>
            {LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '12px',
                  textTransform: 'uppercase',
                  letterSpacing: 'var(--tracking-label)',
                  color: 'var(--text-secondary)',
                }}
              >
                {l.label}
              </a>
            ))}
          </div>

          <IconButton
            label={themeMeta.label}
            size="sm"
            onClick={onToggleTheme}
          >
            <ThemeIcon size={16} strokeWidth={1.8} />
          </IconButton>

          <button
            onClick={() => setOpen((v) => !v)}
            className="ds-nav-toggle"
            aria-label="Toggle navigation"
            style={{
              display: 'none',
              background: 'transparent',
              border: '1.5px solid var(--border-default)',
              borderRadius: 'var(--radius-md)',
              width: 36,
              height: 36,
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-primary)',
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {open && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '2px',
            padding: '0 var(--gutter) 16px',
            background: 'var(--surface-page)',
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              onClick={() => setOpen(false)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                textTransform: 'uppercase',
                letterSpacing: 'var(--tracking-label)',
                color: 'var(--text-secondary)',
                padding: '10px 2px',
              }}
            >
              {l.label}
            </a>
          ))}
        </div>
      )}

      <style>{`
        @media (max-width: 720px) {
          .ds-nav-links { display: none !important; }
          .ds-nav-toggle { display: inline-flex !important; }
        }
      `}</style>
    </div>
  );
}
