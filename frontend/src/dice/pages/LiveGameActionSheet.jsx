import React, { useEffect, useId, useState } from 'react';
import { Button } from '@/components/ui/button';
import PlayerAvatar from '../components/PlayerAvatar.jsx';

const shortId = (value) => {
  const text = String(value || '');
  return text.split('-').length === 5 ? text.slice(-4) : text.split('-')[0];
};

export default function LiveGameActionSheet({ target, game, roster, selectedThrowerId, replayOfEventId, playerLabel = shortId, playerProfile, saving, onCommand, onCancel }) {
  const resultMode = target === 'result' || target === 'fifa';
  const correction = target !== 'game' && !resultMode ? target : null;
  const [step, setStep] = useState(correction ? 'change' : resultMode ? 'result' : 'menu');
  const [outcome, setOutcome] = useState(correction?.outcome || 'miss');
  const [characteristics, setCharacteristics] = useState(correction?.characteristics || []);
  const [thrower, setThrower] = useState(correction?.thrower_id || selectedThrowerId || roster[0]?.playerId || '');
  const [advancedOutcome, setAdvancedOutcome] = useState(target === 'fifa' ? 'fifa' : 'sink');
  const [fifaFinish, setFifaFinish] = useState(null);
  const [fifaKicker, setFifaKicker] = useState('');
  const [score, setScore] = useState(game.score.map(String));
  const [coverage, setCoverage] = useState(game.detail_coverage === 'complete' ? 'partial' : game.detail_coverage);
  const [reason, setReason] = useState(game.status === 'ready_to_finish' ? 'target_reached' : 'other');
  const [responsible, setResponsible] = useState(roster[0]?.playerId || '');
  const titleId = useId();
  const selected = roster.find(({ playerId }) => playerId === responsible);
  const losingIndex = selected ? game.team_order.indexOf(selected.teamId) : 0;
  const offRoofScore = losingIndex === 0 ? '0–5' : '5–0';
  const sheetTitle = correction ? 'Fix result' : step === 'menu' ? 'Game options' : step === 'result' ? (target === 'fifa' ? 'FIFA' : 'More results') : step.replaceAll('_', ' ');
  const throwerTeamId = roster.find(({ playerId }) => playerId === thrower)?.teamId;
  const fifaRoster = throwerTeamId ? roster.filter(({ teamId }) => teamId !== throwerTeamId) : [];
  const savingTeam = throwerTeamId ? roster.filter(({ teamId }) => teamId === throwerTeamId) : [];
  useEffect(() => {
    setFifaFinish(null);
    setFifaKicker('');
  }, [thrower]);
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !saving) onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCancel, saving]);
  const toggleCharacteristic = (value) => setCharacteristics((current) => current.includes(value)
    ? current.filter((item) => item !== value) : [...current, value]);
  const recordFifa = (fifa) => onCommand({
    kind: 'record_throw',
    thrower_id: thrower,
    outcome: 'fifa',
    ...(replayOfEventId ? { replay_of: replayOfEventId } : {}),
    fifa,
  });
  const fifaPlayerButtons = (legend, players, onPick, selectedId = '') => (
    <fieldset className="mt-4">
      <legend className="jk-label">{legend}</legend>
      <div className="grid grid-cols-2 gap-2 mt-2">
        {players.map(({ playerId }) => (
          <button
            key={playerId}
            type="button"
            aria-label={`${legend}: ${playerLabel(playerId)}`}
            aria-pressed={selectedId === playerId}
            disabled={saving}
            className="min-w-0 min-h-16 p-3 rounded-lg border flex items-center gap-3 text-left transition-transform active:scale-[.97]"
            onClick={() => onPick(playerId)}
            style={{
              borderColor: selectedId === playerId ? 'var(--accent-gold)' : 'var(--border-subtle)',
              background: selectedId === playerId ? 'color-mix(in srgb, var(--accent-gold) 15%, var(--surface-card))' : 'var(--surface-card)',
            }}
          >
            <PlayerAvatar profile={playerProfile?.(playerId) || { user_id: playerId, display_name: playerLabel(playerId) }} size={40} linkToProfile={false} />
            <span className="font-semibold truncate">{playerLabel(playerId).split(' ')[0]}</span>
          </button>
        ))}
      </div>
    </fieldset>
  );
  const characteristicControls = () => (
    <fieldset className="mt-3">
      <legend className="jk-label">Invalid characteristics</legend>
      <div className="grid grid-cols-2 gap-2 mt-1">
        {['short', 'low'].map((value) => (
          <label key={value} className="flex items-center gap-2 p-3 rounded-md border capitalize">
            <input type="checkbox" checked={characteristics.includes(value)} onChange={() => toggleCharacteristic(value)} />
            {value}
          </label>
        ))}
      </div>
    </fieldset>
  );

  const select = (id, label, value, setter, options) => (
    <label className="jk-label block mt-3" htmlFor={id}>{label}
      <select id={id} className="block w-full mt-1 p-3 rounded-md border text-base normal-case" value={value} onChange={(event) => setter(event.target.value)}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onCancel(); }} style={{ background: 'rgba(2,2,10,.48)' }}>
      <section role="dialog" aria-modal="true" aria-labelledby={titleId} className="jk-live-action-sheet w-full max-w-xl max-h-[88vh] overflow-y-auto rounded-t-2xl p-5" onMouseDown={(event) => event.stopPropagation()} style={{ background: 'var(--surface-card)' }}>
        <div className="flex items-start justify-between gap-3">
        {correction && <p className="jk-label">{playerLabel(correction.thrower_id)} · {correction.outcome}</p>}
          <Button variant="ghost" size="sm" aria-label="Close game actions" onClick={onCancel}>Close</Button>
        </div>
        <h2 id={titleId} className="jk-display text-3xl mt-2 capitalize">{sheetTitle}</h2>

        {correction && step === 'change' && <>
          <p className="text-sm mt-2">Edit the call, or retoss if they’ll throw again.</p>
          {select('replacement-thrower', 'Replacement thrower', thrower, setThrower, roster.map(({ playerId }) => ({ value: playerId, label: playerLabel(playerId) })))}
          {select('replacement-outcome', 'Replacement result', outcome, setOutcome, ['point', 'miss', 'caught', 'sink', 'self_sink', 'invalid'].map((value) => ({ value, label: value.replaceAll('_', ' ') })))}
          {outcome === 'invalid' && characteristicControls()}
          <Button className="w-full min-h-12 mt-4" disabled={saving || (outcome === 'invalid' && characteristics.length === 0)} onClick={() => onCommand({ kind: 'change_throw', target_event_id: correction.id, thrower_id: thrower, outcome, ...(outcome === 'invalid' ? { characteristics } : {}), reason: 'mistaken_entry' })}>Change result</Button>
          <div className="grid grid-cols-2 gap-2 mt-2"><Button variant="outline" onClick={() => setStep('retoss')}>Retoss — new physical throw</Button><Button variant="outline" onClick={() => setStep('remove')}>Remove mistaken entry</Button></div>
        </>}

        {step === 'retoss' && <>
          <p className="font-semibold mt-4">Retoss for {playerLabel(correction.thrower_id)}?</p>
          <p className="text-sm mt-2">The old throw won’t count. The next one will.</p>
          <Button className="w-full min-h-12 mt-4" disabled={saving} onClick={() => onCommand({ kind: 'retoss', target_event_id: correction.id, thrower_id: correction.thrower_id, decision_basis: 'teams_agreed', disputed_calls: [] })}>Confirm new physical retoss</Button>
        </>}

        {step === 'remove' && <>
          <p className="font-semibold mt-4">Remove {playerLabel(correction.thrower_id)}’s {correction.outcome}?</p>
          <p className="text-sm mt-2">The score will update. History stays intact.</p>
          <Button className="w-full min-h-12 mt-4" disabled={saving} onClick={() => onCommand({ kind: 'remove_mistake', target_event_id: correction.id, reason: 'mistaken_entry' })}>Confirm remove mistaken entry</Button>
        </>}

        {step === 'menu' && <div className="grid gap-2 mt-4">
          <Button variant={game.status === 'ready_to_finish' ? 'default' : 'outline'} className="min-h-12" onClick={() => setStep('finish')}>Finish game</Button>
          <Button variant="outline" className="min-h-12" onClick={() => setStep('fix_score')}>Catch up score</Button>
          <Button variant="ghost" className="min-h-12" onClick={() => setStep('off_roof')}>Off roof · immediate 0–5 loss</Button>
        </div>}

        {step === 'result' && <>
          <div className="mt-3 p-3 rounded-md" aria-label="Advanced result attribution" style={{ background: 'var(--surface-sunken)' }}>
            <p className="jk-label">THROWER</p>
            <p className="font-semibold mt-1">{playerLabel(thrower)}</p>
          </div>
          {target !== 'fifa' && select('advanced-result', 'Result', advancedOutcome, setAdvancedOutcome, [
            { value: 'sink', label: 'Sink' },
            { value: 'self_sink', label: 'Self-sink' },
            { value: 'fifa', label: 'FIFA' },
            { value: 'invalid', label: 'Invalid (short / low)' },
          ])}
          {advancedOutcome === 'invalid' && characteristicControls()}
          {advancedOutcome === 'fifa' && <>
            <fieldset className="mt-4">
              <legend className="jk-label">WHAT HAPPENED?</legend>
              <div className="grid grid-cols-3 gap-2 mt-2">
                {[
                  ['goal', 'Goal', '+1'],
                  ['kick_catch', 'Catch', '+1'],
                  ['goal_saved', 'Saved', '0'],
                ].map(([value, label, points]) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={fifaFinish === value}
                    disabled={saving}
                    className="min-h-14 px-2 rounded-lg border font-semibold transition-transform active:scale-[.97]"
                    onClick={() => { setFifaFinish(value); setFifaKicker(''); }}
                    style={{
                      borderColor: fifaFinish === value ? 'var(--accent-gold)' : 'var(--border-subtle)',
                      background: fifaFinish === value ? 'var(--accent-gold)' : 'var(--surface-card)',
                      color: fifaFinish === value ? 'var(--ink-950)' : 'var(--text-primary)',
                    }}
                  >
                    <span className="block">{label}</span>
                    <span className="block text-xs opacity-70">{points}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            {fifaFinish === 'goal' && fifaPlayerButtons('WHO SCORED?', fifaRoster, (playerId) => recordFifa({ finish: 'goal', kicker_id: playerId }))}
            {fifaFinish === 'kick_catch' && fifaPlayerButtons('WHO CAUGHT IT?', fifaRoster, (catcherId) => recordFifa({
              finish: 'kick_catch',
              kicker_id: fifaRoster.find(({ playerId }) => playerId !== catcherId)?.playerId,
              catcher_id: catcherId,
            }))}
            {fifaFinish === 'goal_saved' && <>
              {fifaPlayerButtons('WHO KICKED IT?', fifaRoster, setFifaKicker, fifaKicker)}
              {fifaKicker && fifaPlayerButtons('WHO SAVED IT?', savingTeam, (saverId) => recordFifa({
                finish: 'goal_saved',
                kicker_id: fifaKicker,
                saver_id: saverId,
              }))}
            </>}
          </>}
          {advancedOutcome !== 'fifa' && <Button className="w-full min-h-12 mt-4" disabled={saving || (advancedOutcome === 'invalid' && characteristics.length === 0)} onClick={() => onCommand({
            kind: 'record_throw', thrower_id: thrower, outcome: advancedOutcome,
            ...(replayOfEventId ? { replay_of: replayOfEventId } : {}),
            ...(advancedOutcome === 'invalid' ? { characteristics } : {}),
          })}>Record {advancedOutcome.replaceAll('_', ' ')}</Button>}
        </>}

        {step === 'fix_score' && <>
          <p className="text-sm mt-2">Missed some plays? Set the score and keep going.</p>
          <div className="grid grid-cols-2 gap-2 mt-4">{score.map((value, index) => <label key={game.team_order[index]} className="jk-label">Team {index + 1}<input aria-label={`Team ${index + 1} score`} className="block w-full mt-1 p-3 rounded-md border text-base" type="number" min="0" value={value} onChange={(event) => setScore((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} /></label>)}</div>
          {select('fix-coverage', 'Observed detail', coverage, setCoverage, [{ value: 'partial', label: 'Partial' }, { value: 'unknown', label: 'Unknown' }])}
          <Button className="w-full min-h-12 mt-4" disabled={saving} onClick={() => onCommand({ kind: 'fix_score', score: score.map(Number), coverage })}>Save known score</Button>
        </>}

        {step === 'finish' && <>
          <p className="text-sm mt-2">Finish at the score shown.</p>
          {select('finish-coverage', 'Stats coverage', coverage, setCoverage, ['complete', 'partial', 'unknown'].map((value) => ({ value, label: value })))}
          {select('finish-reason', 'Termination reason', reason, setReason, ['target_reached', 'time_limit', 'mutual_end', 'forfeit', 'other'].map((value) => ({ value, label: value.replaceAll('_', ' ') })))}
          <Button className="w-full min-h-12 mt-4" disabled={saving} onClick={() => onCommand({ kind: 'finish', coverage, termination_reason: reason })}>Confirm finish at {game.score.join('–')}</Button>
        </>}

        {step === 'off_roof' && <>
          <p className="text-sm mt-2">Pick who caused it. Their team loses {offRoofScore}.</p>
          {select('responsible-player', 'Responsible player', responsible, setResponsible, roster.map(({ playerId }) => ({ value: playerId, label: playerLabel(playerId) })))}
          <Button variant="outline" className="w-full min-h-12 mt-4" onClick={() => setStep('confirm_off_roof')}>Review immediate loss</Button>
        </>}
        {step === 'confirm_off_roof' && <>
          <p className="font-semibold mt-4">Confirm {playerLabel(responsible)} caused an off-roof {offRoofScore} loss?</p>
          <p className="text-sm mt-2">This ends the game now.</p>
          <Button className="w-full min-h-12 mt-4" disabled={saving} style={{ background: 'var(--state-danger)', color: '#fff' }} onClick={() => onCommand({ kind: 'off_roof', responsible_player_id: responsible })}>Confirm off-roof {offRoofScore} completion</Button>
        </>}

        <Button variant="ghost" className="w-full min-h-12 mt-3" onClick={step === 'change' || step === 'menu' || step === 'result' ? onCancel : () => setStep(correction ? 'change' : 'menu')}>Cancel</Button>
      </section>
    </div>
  );
}
