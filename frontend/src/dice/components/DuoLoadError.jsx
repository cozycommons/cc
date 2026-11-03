export default function DuoLoadError({ onRetry }) {
  return (
    <div className="jk-card px-3 py-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
      Couldn't load duos · <button type="button" className="underline" onClick={onRetry}>Retry</button>
    </div>
  );
}
