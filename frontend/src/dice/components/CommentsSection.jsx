import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useSupabase } from '../../contexts/SupabaseContext';
import { diceApi } from '../api.js';
import { formatDateTime } from '../utils.js';
import {
  COMMENT_IMAGE_MAX_EDGE,
  COMMENT_THUMB_MAX_EDGE,
  compactImageVariants,
  imageVariantUrl,
  uniqueImageFolder,
} from '../imageUpload.js';
import PlayerAvatar from './PlayerAvatar.jsx';

const COMMENT_IMAGE_BUCKET = 'dice-comment-photos';

export default function CommentsSection({ gameId, auth }) {
  const { supabase } = useSupabase();
  const { user, token, isAdmin } = auth;
  const [comments, setComments] = useState(null);
  const [body, setBody] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    diceApi.getComments(gameId).then(setComments).catch(() => setComments([]));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameId]);

  useEffect(() => {
    return () => {
      if (imagePreview) URL.revokeObjectURL(imagePreview);
    };
  }, [imagePreview]);

  const handleImageChange = (e) => {
    const file = e.target.files?.[0] || null;
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageFile(file);
    setImagePreview(file ? URL.createObjectURL(file) : null);
  };

  const clearImage = () => {
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageFile(null);
    setImagePreview(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmed = body.trim();
    if (!trimmed && !imageFile) return;
    if (!token || !user) return;
    setSubmitting(true);
    setError(null);
    try {
      let imageUrl = null;
      if (imageFile) {
        const [displayImage, thumbnail] = await compactImageVariants(imageFile, [
          { maxEdge: COMMENT_IMAGE_MAX_EDGE },
          { maxEdge: COMMENT_THUMB_MAX_EDGE, quality: 0.74 },
        ]);
        const folder = uniqueImageFolder(user.id);
        const uploads = [
          [`${folder}/original`, imageFile, imageFile.type],
          [`${folder}/display.webp`, displayImage, 'image/webp'],
          [`${folder}/thumb.webp`, thumbnail, 'image/webp'],
        ];
        await Promise.all(uploads.map(async ([path, bodyToUpload, contentType]) => {
          const { error: uploadError } = await supabase.storage
            .from(COMMENT_IMAGE_BUCKET)
            .upload(path, bodyToUpload, {
              contentType,
              cacheControl: '31536000',
              upsert: false,
            });
          if (uploadError) throw uploadError;
        }));
        const displayPath = `${folder}/display.webp`;
        const { data } = supabase.storage.from(COMMENT_IMAGE_BUCKET).getPublicUrl(displayPath);
        imageUrl = data.publicUrl;
      }
      await diceApi.postComment(token, gameId, trimmed || null, imageUrl);
      setBody('');
      clearImage();
      load();
    } catch (err) {
      const expectedMessage = err?.message?.startsWith('Use a ')
        || err?.message?.startsWith('Image must')
        || err?.message?.startsWith('That image')
        || err?.message?.startsWith('This browser');
      setError(expectedMessage ? err.message : 'Failed to post comment.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (commentId) => {
    if (!window.confirm('Delete this comment?')) return;
    try {
      await diceApi.deleteComment(token, commentId);
      load();
    } catch (err) {
      setError('Failed to delete comment.');
    }
  };

  return (
    <div className="mt-6">
      <p className="jk-label mb-3">// COMMENTS</p>

      <div className="jk-card overflow-hidden mb-4">
        {comments === null && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>
        )}
        {comments?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No comments yet.</p>
        )}
        {comments?.map((c) => {
          const canDelete = user && (isAdmin || c.user_id === user.id);
          return (
            <div key={c.id} className="flex items-start gap-3 px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <PlayerAvatar profile={c} size={32} linkToProfile={false} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span style={{ fontFamily: 'var(--font-body)', fontWeight: 500, fontSize: 13, color: 'var(--text-primary)' }}>
                    {c.display_name}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}>
                    {formatDateTime(c.created_at)}
                  </span>
                </div>
                {c.body && (
                  <p className="mt-0.5" style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                    {c.body}
                  </p>
                )}
                {c.image_url && (
                  <a
                    href={imageVariantUrl(c.image_url, 'original')}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block mt-2"
                    style={{ width: 'min(240px, 100%)' }}
                  >
                    <img
                      src={c.image_url}
                      alt=""
                      width={240}
                      height={180}
                      loading="lazy"
                      decoding="async"
                      style={{
                        width: '100%',
                        height: 'auto',
                        maxHeight: 240,
                        borderRadius: 'var(--radius-md)',
                        border: '1px solid var(--border-subtle)',
                        display: 'block',
                      }}
                    />
                  </a>
                )}
              </div>
              {canDelete && (
                <button
                  type="button"
                  onClick={() => handleDelete(c.id)}
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}
                >
                  delete
                </button>
              )}
            </div>
          );
        })}
      </div>

      {user ? (
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Add a comment…"
            maxLength={2000}
            rows={2}
            className="w-full px-3 py-2"
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 14,
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-md)',
              background: 'var(--surface-card)',
              color: 'var(--text-primary)',
              resize: 'vertical',
            }}
          />

          {imagePreview && (
            <div className="relative inline-block" style={{ width: 'fit-content' }}>
              <img
                src={imagePreview}
                alt=""
                style={{ maxWidth: 160, maxHeight: 160, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', display: 'block' }}
              />
              <button
                type="button"
                onClick={clearImage}
                className="absolute -top-2 -right-2 flex items-center justify-center"
                style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--surface-strong)', color: 'var(--text-on-strong)', fontSize: 13 }}
                aria-label="Remove image"
              >
                ×
              </button>
            </div>
          )}

          <div className="flex items-center justify-between gap-2">
            <label
              className="cursor-pointer"
              style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-tertiary)' }}
            >
              📷 Attach photo
              <input type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={handleImageChange} />
            </label>
            <Button
              type="submit"
              size="sm"
              disabled={submitting || (!body.trim() && !imageFile)}
              style={{ background: 'var(--accent-primary)', color: '#fff' }}
            >
              {submitting ? 'Posting…' : 'Post Comment'}
            </Button>
          </div>
          {error && <p style={{ color: 'var(--state-danger)', fontSize: 13 }}>{error}</p>}
        </form>
      ) : (
        <p style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-tertiary)' }}>
          Sign in to comment.
        </p>
      )}
    </div>
  );
}
