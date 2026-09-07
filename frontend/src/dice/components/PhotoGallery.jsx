import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { diceApi } from '../api.js';
import { formatDateTime } from '../utils.js';
import { imageVariantUrl } from '../imageUpload.js';

export function getSwipeDirection(start, end) {
  if (!start || !end) return null;
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  if (Math.abs(deltaX) < 50 || Math.abs(deltaX) <= Math.abs(deltaY)) return null;
  return deltaX < 0 ? 1 : -1;
}

function Lightbox({ photos, selectedIndex, onNavigate, onClose }) {
  const photo = photos[selectedIndex];
  const hasMultiplePhotos = photos.length > 1;
  const dialogRef = useRef(null);
  const closeButtonRef = useRef(null);
  const pointerStart = useRef(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previouslyFocused = document.activeElement;

    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    closeButtonRef.current?.focus();

    return () => {
      if (dialog.open && typeof dialog.close === 'function') {
        dialog.close();
      } else {
        dialog.removeAttribute('open');
      }
      previouslyFocused?.focus?.();
    };
  }, []);

  const handlePointerDown = (event) => {
    if (!hasMultiplePhotos || event.isPrimary === false) return;
    pointerStart.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const handlePointerUp = (event) => {
    const start = pointerStart.current;
    pointerStart.current = null;
    if (!start) return;

    const direction = getSwipeDirection(start, { x: event.clientX, y: event.clientY });
    if (direction) onNavigate(direction);
  };

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft' && hasMultiplePhotos) onNavigate(-1);
      if (e.key === 'ArrowRight' && hasMultiplePhotos) onNavigate(1);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [hasMultiplePhotos, onClose, onNavigate]);

  return (
    <dialog
      ref={dialogRef}
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{
        width: '100%',
        height: '100%',
        maxWidth: 'none',
        maxHeight: 'none',
        margin: 0,
        border: 0,
        background: 'rgba(2, 2, 10, 0.85)',
        zIndex: 100,
      }}
      onClick={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Photo viewer"
    >
      <div
        className="flex flex-col items-center max-w-full max-h-full"
        onClick={(e) => e.stopPropagation()}
      >
        {hasMultiplePhotos && (
          <button
            type="button"
            onClick={() => onNavigate(-1)}
            aria-label="Previous photo"
            className="absolute left-3 sm:left-6 top-1/2 -translate-y-1/2 flex items-center justify-center"
            style={{
              width: 44,
              height: 44,
              borderRadius: '50%',
              background: 'rgba(255,255,255,0.15)',
              color: '#fff',
            }}
          >
            <ChevronLeft className="w-6 h-6" />
          </button>
        )}
        <img
          src={photo.image_url}
          alt={`Photo by ${photo.display_name}`}
          className="max-w-full"
          style={{
            maxHeight: '75vh',
            borderRadius: 'var(--radius-md)',
            display: 'block',
            touchAction: 'pan-y',
            userSelect: 'none',
          }}
          draggable={false}
          decoding="async"
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerCancel={() => { pointerStart.current = null; }}
        />
        {hasMultiplePhotos && (
          <button
            type="button"
            onClick={() => onNavigate(1)}
            aria-label="Next photo"
            className="absolute right-3 sm:right-6 top-1/2 -translate-y-1/2 flex items-center justify-center"
            style={{
              width: 44,
              height: 44,
              borderRadius: '50%',
              background: 'rgba(255,255,255,0.15)',
              color: '#fff',
            }}
          >
            <ChevronRight className="w-6 h-6" />
          </button>
        )}
        <div className="w-full mt-3 px-1">
          <div className="min-w-0">
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--paper-50)' }}>
              {photo.display_name} · {formatDateTime(photo.created_at)}
            </div>
            {hasMultiplePhotos && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.7)', marginTop: 2 }}>
                {selectedIndex + 1} / {photos.length}
              </div>
            )}
          </div>
          <div className="flex items-center justify-between gap-4 mt-2">
            <a
              href={imageVariantUrl(photo.image_url, 'original', true)}
              style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--paper-50)', whiteSpace: 'nowrap' }}
            >
              Download original
            </a>
            <Link
              to={`/dice/game/${photo.game_id}`}
              style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--paper-50)', whiteSpace: 'nowrap' }}
            >
              View game →
            </Link>
          </div>
        </div>
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 flex items-center justify-center"
          style={{ width: 32, height: 32, borderRadius: '50%', background: 'rgba(255,255,255,0.15)', color: '#fff', fontSize: 18 }}
        >
          ×
        </button>
      </div>
    </dialog>
  );
}

export default function PhotoGallery({ limit = 100 }) {
  const [photos, setPhotos] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(null);

  const navigatePhotos = (direction) => {
    if (!photos?.length) return;
    setSelectedIndex((current) => (current + direction + photos.length) % photos.length);
  };

  useEffect(() => {
    diceApi.getPhotos(limit).then(setPhotos).catch(() => setPhotos([]));
  }, [limit]);

  return (
    <>
      <div className="jk-card overflow-hidden p-2">
        {photos === null && <p className="p-2 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
        {photos?.length === 0 && (
          <p className="p-2 text-sm" style={{ color: 'var(--text-tertiary)' }}>No photos posted yet.</p>
        )}
        {photos?.length > 0 && (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
            {photos.map((p, index) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setSelectedIndex(index)}
                className="aspect-square overflow-hidden"
                style={{
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  padding: 0,
                  background: 'transparent',
                  cursor: 'pointer',
                }}
                aria-label={`Open photo ${index + 1} of ${photos.length}`}
              >
                <img
                  src={imageVariantUrl(p.image_url, 'thumb')}
                  alt={`Photo by ${p.display_name}`}
                  className="w-full h-full"
                  loading={index < 6 ? 'eager' : 'lazy'}
                  decoding="async"
                  style={{ objectFit: 'cover', display: 'block' }}
                />
              </button>
            ))}
          </div>
        )}
      </div>
      {selectedIndex !== null && photos?.[selectedIndex] && (
        <Lightbox
          photos={photos}
          selectedIndex={selectedIndex}
          onNavigate={navigatePhotos}
          onClose={() => setSelectedIndex(null)}
        />
      )}
    </>
  );
}
