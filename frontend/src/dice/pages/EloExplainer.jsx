import React from 'react';
import { Link } from 'react-router-dom';

function P({ children }) {
  return (
    <p className="mb-3" style={{ fontFamily: 'var(--font-body)', fontSize: 14, lineHeight: 1.6, color: 'var(--text-secondary)' }}>
      {children}
    </p>
  );
}

export default function EloExplainer() {
  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
      <Link className="jk-label inline-block underline mb-5" to="/dice/leaderboard/elo">← ELO leaderboard</Link>
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>How ELO works</p>
      <div className="jk-card p-5">
        <P>
          Everyone starts at <strong>1500 ELO</strong>. Win ranked games and climb. Lose, and you give some back.
          Normal games still count toward your record, but they never move your ELO.
        </P>
        <P>
          Not every win is equal. Beat a stronger team or win big and you earn more. Win a matchup you were
          expected to win, or squeak out a close one, and the move is smaller. One great result can matter,
          but no single game can blow up your rating.
        </P>
        <P>
          Your first <strong>3 ranked games</strong> are placements. Your rating moves faster while the system
          learns your level, then settles as it gets more confident. A long break never changes your ELO by
          itself — it just lets your next result say a little more.
        </P>
        <P>
          If an old result gets corrected, we rebuild the rankings from the games that actually happened.
          The leaderboard stays fair, current, and earned.
        </P>
      </div>
    </div>
  );
}
