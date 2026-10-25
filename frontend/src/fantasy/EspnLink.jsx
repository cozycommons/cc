import React, { createContext, useContext } from 'react';
import { playerProfile } from './espn.js';

export const LeagueLinksContext = createContext(null);

export default function EspnLink({ href, children }) {
  if (!href) return null;
  return <a className="fx-espn-link" href={href} rel="noreferrer"><span className="fx-espn-badge" aria-hidden="true">ESPN</span>{children}</a>;
}

export function PlayerLink({ id, name }) {
  return <EspnLink href={playerProfile(id)}>{name}</EspnLink>;
}

export function MatchupLink({ matchup }) {
  const links = useContext(LeagueLinksContext);
  return <EspnLink href={links?.matchups?.[matchup.home.id]}>Matchup in ESPN</EspnLink>;
}

export function TeamLinks({ teamId }) {
  const links = useContext(LeagueLinksContext);
  if (links?.team_id !== teamId) return null;
  return <div className="fx-espn-actions"><EspnLink href={links.team}>Your team</EspnLink><EspnLink href={links.lineup}>Set lineup</EspnLink><EspnLink href={links.free_agents}>Free agents</EspnLink></div>;
}
