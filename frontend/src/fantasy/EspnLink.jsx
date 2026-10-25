import React, { createContext, useContext } from 'react';
import { playerProfile } from './espn.js';

export const LeagueLinksContext = createContext(null);

// ESPN's own red logo, served from ESPN's CDN.
const ESPN_LOGO = 'https://a.espncdn.com/combiner/i?img=/i/espn/espn_logos/espn_red.png&w=80';

export function EspnLogo() {
  return <img className="fx-espn-logo" src={ESPN_LOGO} alt="" aria-hidden="true" width="25" height="14" loading="lazy" referrerPolicy="no-referrer" />;
}

export default function EspnLink({ href, children, badge = true, button = false }) {
  if (!href) return null;
  return <a className={`fx-espn-link${button ? ' fx-espn-button' : ''}`} href={href} rel="noreferrer">{badge && <EspnLogo />}{children}</a>;
}

export function PlayerLink({ id, name, badge = false }) {
  return <EspnLink href={playerProfile(id)} badge={badge}>{name}</EspnLink>;
}

export function MatchupLink({ matchup }) {
  const links = useContext(LeagueLinksContext);
  return <EspnLink href={links?.matchups?.[matchup.home.id]} button>Matchup</EspnLink>;
}

export function TeamLinks({ teamId }) {
  const links = useContext(LeagueLinksContext);
  if (links?.team_id !== teamId) return null;
  return <div className="fx-espn-actions"><EspnLink href={links.team} button>Your team</EspnLink><EspnLink href={links.lineup} button>Set lineup</EspnLink><EspnLink href={links.free_agents} button>Free agents</EspnLink></div>;
}
