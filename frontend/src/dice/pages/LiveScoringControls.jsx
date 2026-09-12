import React from 'react';
import { Button } from '@/components/ui/button';
import PlayerAvatar from '../components/PlayerAvatar.jsx';

const teamTone = (teamId, leftTeamId) => (teamId === leftTeamId ? 'var(--team1-color)' : 'var(--team2-color)');

export default function LiveScoringControls({
  roster,
  throwOrder,
  turnKnown,
  leftTeamId,
  effectiveThrowerId,
  throwerSelectionLocked,
  playerLabel,
  playerProfile,
  joined,
  saving,
  onSelectThrower,
  onRecord,
  onTableHit,
  onFifa,
  onMoreResults,
}) {
  const orderedRoster = (throwOrder || [])
    .map((playerId) => roster.find((player) => player.playerId === playerId))
    .filter(Boolean);
  const visibleRoster = orderedRoster.length === roster.length ? orderedRoster : roster;
  const hasSelectedThrower = Boolean(effectiveThrowerId);
  return (
    <section className="jk-card jk-live-scoring-controls mt-5 overflow-hidden" aria-label="Live scoring controls">
      <div className="p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="jk-label">WHO THREW?</p>
          {!turnKnown && !hasSelectedThrower && <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>Order unknown · choose thrower</p>}
        </div>
        <p className="sr-only" aria-live="polite">{hasSelectedThrower ? `Next thrower: ${playerLabel(effectiveThrowerId)}` : 'Next thrower unknown. Choose a player.'}</p>
        <div className="grid grid-cols-2 gap-2 mt-2">
          {visibleRoster.map(({ teamId, playerId }, turnIndex) => {
            const active = effectiveThrowerId === playerId;
            const tone = teamTone(teamId, leftTeamId);
            return (
              <button
                type="button"
                key={playerId}
                onClick={() => onSelectThrower(playerId)}
                disabled={throwerSelectionLocked}
                aria-pressed={active}
                aria-label={playerLabel(playerId)}
                className="jk-live-player-choice min-h-16 px-2 py-2 rounded-md text-left font-semibold transition-all duration-200 flex items-center gap-2"
                style={{
                  border: `1.5px solid ${active ? tone : 'var(--border-subtle)'}`,
                  background: active
                    ? `color-mix(in srgb, ${tone} 13%, var(--surface-card))`
                    : 'var(--surface-card)',
                  boxShadow: `inset ${active ? 5 : 3}px 0 0 ${tone}`,
                }}
              >
                <span className={`relative shrink-0 transition-transform duration-200 ${active ? 'scale-105' : ''}`}>
                  <PlayerAvatar profile={playerProfile(playerId)} size={42} linkToProfile={false} />
                  {turnKnown && <span
                    aria-hidden="true"
                    className="absolute -top-1 -left-1 w-4 h-4 rounded-full grid place-items-center text-[9px] font-bold"
                    style={{ background: tone, color: 'var(--surface-card)' }}
                  >{turnIndex + 1}</span>}
                </span>
                <span className="truncate">{playerLabel(playerId).split(' ')[0]}</span>
              </button>
            );
          })}
        </div>

        <div className="jk-live-result-step mt-5 pt-4" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <p className="jk-label">WHAT HAPPENED?</p>
          {!joined ? (
            <p className="mt-2 p-3 rounded-md text-sm" style={{ background: 'var(--surface-sunken)' }}>
              Join from the live games list before recording a result.
            </p>
          ) : (
            <>
              <div className="jk-live-result-grid grid grid-cols-2 gap-2 mt-2">
                <Button
                  className="jk-live-result-button min-h-14 px-2"
                  aria-label="Point"
                  disabled={saving || !hasSelectedThrower}
                  onClick={() => onRecord('point')}
                  style={{ background: 'var(--surface-strong)', color: 'var(--text-on-strong)' }}
                >
                  Point <span className="ml-1 opacity-70">+1</span>
                </Button>
                <Button className="jk-live-result-button min-h-14 px-2" variant="outline" disabled={saving || !hasSelectedThrower} onClick={onTableHit}>Table hit</Button>
                <Button
                  className="jk-live-result-button min-h-14 px-2"
                  disabled={saving || !hasSelectedThrower}
                  onClick={onFifa}
                  style={{ background: 'var(--accent-gold)', color: 'var(--ink-950)' }}
                >FIFA <span className="ml-1 opacity-70">+1</span></Button>
                <Button className="jk-live-result-button min-h-14 px-2" variant="outline" disabled={saving || !hasSelectedThrower} onClick={() => onRecord('miss')}>Miss</Button>
              </div>
              <button
                type="button"
                className="w-full mt-3 py-2 text-sm font-semibold underline underline-offset-4"
                aria-label="More results"
                disabled={saving || !hasSelectedThrower}
                onClick={onMoreResults}
              >More</button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
