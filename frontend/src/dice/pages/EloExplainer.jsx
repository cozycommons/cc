import React from 'react';

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
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>How ELO works</p>
      <div className="jk-card p-5">
        <P>
          Every player starts at <strong>1500 ELO</strong>. Only <strong>ranked</strong> matches move your rating —
          normal matches still count toward your wins/losses and history, but leave ELO untouched.
        </P>
        <P>
          A team's rating is the average of its two players' ratings. Before a ranked match, we work out each
          team's <em>expected</em> chance of winning from the gap between the two team ratings — a 100-point edge
          gives a team roughly a 64% expected win rate, 400 points is roughly 91%.
        </P>
        <P>
          After the match, everyone's rating shifts based on how surprising the result was:
          winning as the underdog gains you more than winning as the favorite, and losing as
          the favorite costs you more than losing as the underdog. Both players on a team move by the same amount
          for that game.
        </P>
        <P>
          The score matters too. Games are played to a target score that can vary night to night, so we treat
          the winning team's score as that game's target and compare the losing team's score to it. A razor-close
          finish barely adds anything on top of the base result, while a shutout (or something close to it) can
          move ratings up to twice as much.
        </P>
        <P>
          New players move faster: for your first 3 ranked games, a bigger adjustment
          (a "K-factor" of 40) is used so your rating finds its true level quickly. After that, the
          K-factor drops to 20 and ratings settle down.
        </P>
        <P>
          Editing or deleting a past ranked match automatically recalculates every ranked match after it in
          chronological order, so the leaderboard is always consistent.
        </P>
      </div>
    </div>
  );
}
