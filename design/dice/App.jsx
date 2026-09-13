import React from 'react';
import './design.css';
import { DesignNav } from './sections/DesignNav';
import { Hero } from './sections/Hero';
import { Foundations } from './sections/Foundations';
import { ComponentGallery } from './sections/ComponentGallery';
import { Prototypes } from './sections/Prototypes';
import { ArtGallery } from './sections/ArtGallery';
import { DesignFooter } from './sections/DesignFooter';

const THEME_KEY = 'jk-design-theme';

const THEME_ORDER = ['light', 'dark', 'jaycee'];

function getInitialTheme() {
  if (typeof window === 'undefined') return 'light';
  const stored = window.localStorage.getItem(THEME_KEY);
  if (THEME_ORDER.includes(stored)) return stored;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function DesignApp() {
  const [theme, setTheme] = React.useState(getInitialTheme);

  React.useEffect(() => {
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const toggleTheme = () => setTheme((t) => THEME_ORDER[(THEME_ORDER.indexOf(t) + 1) % THEME_ORDER.length]);

  return (
    <div className="jk-design" data-theme={theme}>
      <DesignNav theme={theme} onToggleTheme={toggleTheme} />
      <Hero />
      <Foundations theme={theme} />
      <ComponentGallery />
      <Prototypes />
      <ArtGallery />
      <DesignFooter />
    </div>
  );
}

export default DesignApp;
