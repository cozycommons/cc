import React, { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import { COLORS, round } from './parts.jsx';
import { finished } from './analysis.js';

export const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
export const sharedName = (matchup, side, part) => reducedMotion() ? undefined : `fx-${matchup.key}-${side}-${part}`;

export function MotionLink({ to, children, ...props }) {
  const navigate = useNavigate();
  return <Link to={to} {...props} onClick={event => {
    if (!document.startViewTransition || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    document.startViewTransition(() => flushSync(() => navigate(to, { relative: 'path' })));
  }}>{children}</Link>;
}

export function Score({ value, side, name }) {
  const node = useRef(null), previous = useRef(0);
  useEffect(() => {
    const element = node.current, start = previous.current;
    if (!window.requestAnimationFrame) { element.textContent = round(value); previous.current = value; return; }
    let frame, at;
    const tick = now => {
      at ??= now;
      const progress = Math.min(1, (now - at) / 600);
      previous.current = start + (value - start) * (1 - (1 - progress) ** 3);
      element.textContent = round(previous.current);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    const flash = start !== 0 && start !== value ? element.parentElement.animate?.([{ opacity: .25 }, { opacity: 0 }], { duration: 600, pseudoElement: '::after' }) : null;
    return () => { cancelAnimationFrame(frame); flash?.cancel(); };
  }, [value]);
  return <span className="fx-score" style={{ '--fx-side': COLORS[side], minWidth: `${String(round(value)).length}ch`, viewTransitionName: name }} aria-label={`${round(value)} points`}><span ref={node} aria-hidden="true">{round(value)}</span></span>;
}

export function OddsBar({ chance, big = false }) {
  return <div className={`fx-bar fx-motion-bar${big ? ' fx-bar--big' : ''}`} aria-hidden="true"><i style={{ transform: `scaleX(${chance / 100})` }} /><i style={{ transform: `scaleX(${1 - chance / 100})` }} /></div>;
}

export function GameStatus({ matchup }) {
  if (finished(matchup)) return null;
  const close = Math.abs(matchup.scores[0] - matchup.scores[1]) <= 10 || (matchup.chance >= 45 && matchup.chance <= 55);
  return <>{close && <span className="fx-chip fx-close">Close one</span>}{matchup.days.some(day => day.state === 'live') && <span className="fx-live" role="img" aria-label="Games in progress" />}</>;
}

export function Confetti({ matchup, side, week }) {
  const [burst, setBurst] = useState(false);
  useEffect(() => {
    if (!finished(matchup) || matchup.scores[side] <= matchup.scores[1 - side] || reducedMotion()) return;
    const key = `fx-final-${week}-${matchup.key}`;
    try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, '1'); } catch { return; }
    setBurst(true);

  }, [matchup, side, week]);
  return burst && <span className="fx-confetti" aria-hidden="true">{Array.from({ length: 12 }, (_, i) => <i key={i} style={{ '--x': `${(i - 5.5) * 13}px`, '--r': `${i * 73}deg`, background: COLORS[i % 2] }} />)}</span>;
}

export function SlidingTabs({ items, active, onSelect, className, label }) {
  const root = useRef(null), indicator = useRef(null);
  useEffect(() => {
    const update = () => {
      const button = root.current.querySelector(`[data-key="${active}"]`);
      if (button) { indicator.current.style.width = `${button.offsetWidth}px`; indicator.current.style.transform = `translateX(${button.offsetLeft}px)`; }
    };
    update();
    const observer = new ResizeObserver(update); observer.observe(root.current);
    return () => observer.disconnect();
  }, [active, items]);
  return <div ref={root} className={`${className} fx-sliding`} role="group" aria-label={label}><i ref={indicator} className="fx-tab-indicator" aria-hidden="true" />{items.map(([key, text]) => <button key={key} data-key={key} type="button" aria-pressed={active === key} onClick={() => onSelect(key)}>{text}</button>)}</div>;
}
