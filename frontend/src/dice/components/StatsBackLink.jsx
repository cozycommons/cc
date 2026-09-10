import React from 'react';
import { Link } from 'react-router-dom';

export default function StatsBackLink({ view, label = 'Stats' }) {
  const to = view ? `/dice/stats?view=${view}` : '/dice/stats';
  return <Link className="jk-label inline-block underline mb-5" to={to}>← {label}</Link>;
}
