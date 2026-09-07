import React from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import PlayerAvatar from './PlayerAvatar.jsx';

// Sized so 3 columns + 2 connectors (COLUMN_WIDTH * 3 + CONNECTOR_WIDTH * 2)
// comfortably fit inside the tournament page's card without needing
// horizontal scroll at its narrowest "sm and up" width (~560px of content
// once the page's own max-width and card padding are subtracted).
const COLUMN_WIDTH = 145;
const TEAM_HEIGHT = 60;
const MID_HEIGHT = 28;
const GAP = 8;
const COLUMN_HEIGHT = TEAM_HEIGHT * 2 + MID_HEIGHT + GAP * 2;
const TEAM1_CENTER = TEAM_HEIGHT / 2;
const TEAM2_CENTER = COLUMN_HEIGHT - TEAM_HEIGHT / 2;
const MID_Y = COLUMN_HEIGHT / 2;
const CONNECTOR_WIDTH = 20;
const BAR_X = CONNECTOR_WIDTH / 2;

function PlayerRow({ player }) {
  return (
    <div className="flex items-center gap-2">
      {player.user_id ? (
        <PlayerAvatar profile={player} size={20} linkToProfile={false} />
      ) : (
        <div
          style={{
            width: 20,
            height: 20,
            flexShrink: 0,
            borderRadius: '50%',
            background: 'var(--surface-sunken)',
            border: '1px dashed var(--border-default)',
          }}
        />
      )}
      <span
        className="truncate"
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 12,
          color: player.user_id ? 'var(--text-primary)' : 'var(--text-tertiary)',
        }}
      >
        {player.display_name}
      </span>
    </div>
  );
}

// One bracket corner: a 2-player team, boxed together so it reads as a
// single unit at that corner of the bracket.
function TeamCard({ team, winner, loser }) {
  return (
    <div
      className="jk-card flex flex-col justify-center gap-1 px-2.5"
      style={{
        width: COLUMN_WIDTH,
        height: TEAM_HEIGHT,
        borderColor: winner ? 'var(--state-success)' : undefined,
        borderWidth: winner ? 2 : 1,
        opacity: loser ? 0.55 : 1,
      }}
    >
      {team.map((player, i) => (
        <PlayerRow key={player.user_id || i} player={player} />
      ))}
    </div>
  );
}

function MidCell({ match, canEnter, onEnterResult }) {
  if (match.game) {
    return (
      <Link
        to={`/dice/game/${match.game.id}`}
        className="jk-display"
        style={{ fontSize: 15, color: 'var(--text-primary)' }}
      >
        {match.game.team1_score}–{match.game.team2_score}
      </Link>
    );
  }
  if (canEnter) {
    return (
      <Button
        size="sm"
        variant="outline"
        onClick={onEnterResult}
        style={{ fontSize: 11, padding: '2px 10px', height: 'auto', whiteSpace: 'nowrap' }}
      >
        Enter Result
      </Button>
    );
  }
  return <span className="jk-label">vs</span>;
}

// The three vertically-stacked pieces (team1 / mid cell / team2) shared by
// every bracket column — semis and the final all use this same fixed
// height so their centers line up with each other and with the connectors.
function BracketColumn({ match, canEnterUser, onEnterResult }) {
  const resolved = Boolean(match.game);
  const bothTeamsSet = [...match.team1, ...match.team2].every((p) => p.user_id);
  const canEnter = canEnterUser && !resolved && bothTeamsSet;
  const winner1 = resolved && match.winner_team === 1;
  const winner2 = resolved && match.winner_team === 2;

  return (
    <div className="flex flex-col" style={{ width: COLUMN_WIDTH, height: COLUMN_HEIGHT, gap: GAP }}>
      <TeamCard team={match.team1} winner={winner1} loser={resolved && !winner1} />
      <div className="flex items-center justify-center" style={{ height: MID_HEIGHT }}>
        <MidCell match={match} canEnter={canEnter} onEnterResult={onEnterResult} />
      </div>
      <TeamCard team={match.team2} winner={winner2} loser={resolved && !winner2} />
    </div>
  );
}

// Draws the two lines from a semi's corners bracketing together into one
// line pointing at the final — an SVG traced against fixed pixel heights
// that match BracketColumn exactly, so the bend always lands on each
// team's vertical center rather than an approximate flex split.
function Connector({ mirrored }) {
  const near = mirrored ? CONNECTOR_WIDTH : 0; // edge touching the semi's teams
  const far = mirrored ? 0 : CONNECTOR_WIDTH; // edge touching the final column
  const d = `M${near},${TEAM1_CENTER} L${BAR_X},${TEAM1_CENTER} L${BAR_X},${TEAM2_CENTER} L${near},${TEAM2_CENTER} M${BAR_X},${MID_Y} L${far},${MID_Y}`;
  return (
    <svg width={CONNECTOR_WIDTH} height={COLUMN_HEIGHT} style={{ flexShrink: 0, display: 'block' }}>
      <path d={d} fill="none" stroke="var(--border-strong)" strokeWidth={2} />
    </svg>
  );
}

function BracketSide({ match, mirrored, canEnterUser, onEnterResult }) {
  const column = <BracketColumn match={match} canEnterUser={canEnterUser} onEnterResult={onEnterResult} />;
  const connector = <Connector mirrored={mirrored} />;
  return (
    <div className="flex items-start">
      {mirrored ? (
        <>
          {connector}
          {column}
        </>
      ) : (
        <>
          {column}
          {connector}
        </>
      )}
    </div>
  );
}

function ChampionSpotlight({ champion }) {
  return (
    <div
      className="mt-6 p-6 sm:p-8 flex flex-col items-center text-center gap-3"
      style={{
        borderRadius: 'var(--radius-xl)',
        background: 'linear-gradient(180deg, color-mix(in srgb, var(--accent-gold) 22%, var(--surface-card)), var(--surface-card))',
        border: '1px solid var(--accent-gold)',
        boxShadow: 'var(--shadow-md)',
      }}
    >
      <span className="jk-label" style={{ color: 'var(--accent-gold-deep)' }}>Champions</span>
      <div className="flex items-center gap-6">
        {champion.map((player) => (
          <div key={player.user_id} className="flex flex-col items-center gap-2">
            <PlayerAvatar profile={player} size={88} linkToProfile={false} />
            <p className="jk-display" style={{ fontSize: 26 }}>{player.display_name}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// Renders the bracket: 4 finalist teams (2 players each) at the outer
// edges, bracketed by connector lines toward the middle, where the
// final's two team slots sit. A champion spotlight appears once the
// final is resolved.
export default function BracketView({ bracket, canEnterUser, onEnterResult }) {
  return (
    <div>
      <div className="w-full overflow-x-auto">
        <div className="flex items-start justify-center mx-auto py-2" style={{ width: 'fit-content', minWidth: '100%' }}>
          <BracketSide
            match={bracket.semi1}
            mirrored={false}
            canEnterUser={canEnterUser}
            onEnterResult={() => onEnterResult('semi1')}
          />
          <BracketColumn
            match={bracket.final}
            canEnterUser={canEnterUser}
            onEnterResult={() => onEnterResult('final')}
          />
          <BracketSide
            match={bracket.semi2}
            mirrored={true}
            canEnterUser={canEnterUser}
            onEnterResult={() => onEnterResult('semi2')}
          />
        </div>
      </div>
      {bracket.champion.length > 0 && <ChampionSpotlight champion={bracket.champion} />}
    </div>
  );
}
