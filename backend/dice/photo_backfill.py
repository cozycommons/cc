"""Backfill compact variants for legacy Dice comment photos and avatars.

Dry-run is the default. Applying is deliberately a one-shot maintenance action;
the web process never invokes this module.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import os
from typing import Callable, Iterable
from urllib.parse import quote, unquote, urlparse
from uuid import UUID

from PIL import Image, ImageOps
from supabase import Client, create_client


BUCKET = "dice-comment-photos"
TABLE = "dice_game_comments"
AVATAR_BUCKET = "dice-profile-photos"
AVATAR_TABLE = "dice_profiles"
DISPLAY_MAX_EDGE = 1600
THUMB_MAX_EDGE = 480
AVATAR_MAX_EDGE = 256
MAX_SOURCE_BYTES = 25 * 1024 * 1024
_PUBLIC_PREFIX = f"/storage/v1/object/public/{BUCKET}/"
_AVATAR_PUBLIC_PREFIX = f"/storage/v1/object/public/{AVATAR_BUCKET}/"
_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


@dataclass(frozen=True)
class PhotoCandidate:
    comment_id: str
    user_id: str
    old_url: str
    source_path: str

    @property
    def target_folder(self) -> str:
        return f"{self.user_id}/backfill-{self.comment_id}"


@dataclass(frozen=True)
class PreparedPhoto:
    original: bytes
    original_content_type: str
    display: bytes
    thumbnail: bytes


@dataclass(frozen=True)
class AvatarCandidate:
    user_id: str
    old_url: str
    source_path: str

    @property
    def target_folder(self) -> str:
        digest = sha256(self.old_url.encode("utf-8")).hexdigest()[:16]
        return f"{self.user_id}/backfill-{digest}"


@dataclass(frozen=True)
class PreparedAvatar:
    original: bytes
    original_content_type: str
    avatar: bytes


def _uuid(value: object, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"invalid {field}") from exc


def candidate_from_row(row: dict, supabase_url: str) -> PhotoCandidate | None:
    image_url = row.get("image_url")
    if not image_url or image_url.endswith("/display.webp"):
        return None

    parsed = urlparse(image_url)
    expected = urlparse(supabase_url.rstrip("/"))
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        raise ValueError(f"comment {row.get('id')} has an external image URL")
    if parsed.query or parsed.fragment or not parsed.path.startswith(_PUBLIC_PREFIX):
        raise ValueError(f"comment {row.get('id')} has an unsupported image URL")

    source_path = unquote(parsed.path[len(_PUBLIC_PREFIX) :])
    segments = source_path.split("/")
    if not source_path or any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"comment {row.get('id')} has an unsafe storage path")

    return PhotoCandidate(
        comment_id=_uuid(row.get("id"), "comment id"),
        user_id=_uuid(row.get("user_id"), "user id"),
        old_url=image_url,
        source_path=source_path,
    )


def find_candidates(rows: Iterable[dict], supabase_url: str) -> list[PhotoCandidate]:
    return [candidate for row in rows if (candidate := candidate_from_row(row, supabase_url))]


def avatar_candidate_from_row(row: dict, supabase_url: str) -> AvatarCandidate | None:
    avatar_url = row.get("avatar_url")
    if not avatar_url or avatar_url.endswith("/avatar.webp"):
        return None

    parsed = urlparse(avatar_url)
    expected = urlparse(supabase_url.rstrip("/"))
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        return None
    if not parsed.path.startswith(_AVATAR_PUBLIC_PREFIX):
        return None
    if parsed.query or parsed.fragment:
        raise ValueError(f"profile {row.get('user_id')} has an unsupported avatar URL")

    source_path = unquote(parsed.path[len(_AVATAR_PUBLIC_PREFIX) :])
    segments = source_path.split("/")
    if not source_path or any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"profile {row.get('user_id')} has an unsafe storage path")

    return AvatarCandidate(
        user_id=_uuid(row.get("user_id"), "user id"),
        old_url=avatar_url,
        source_path=source_path,
    )


def find_avatar_candidates(rows: Iterable[dict], supabase_url: str) -> list[AvatarCandidate]:
    return [candidate for row in rows if (candidate := avatar_candidate_from_row(row, supabase_url))]


def _webp(image: Image.Image, max_edge: int, quality: int) -> bytes:
    compact = image.copy()
    compact.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    compact.save(output, format="WEBP", quality=quality, method=6)
    return output.getvalue()


def prepare_photo(source: bytes) -> PreparedPhoto:
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("source photo must be between 1 byte and 25 MiB")

    with Image.open(BytesIO(source)) as opened:
        content_type = _CONTENT_TYPES.get(opened.format or "")
        if content_type is None:
            raise ValueError("legacy photo must be JPEG/MPO, PNG, or WebP")
        normalized = ImageOps.exif_transpose(opened)
        normalized.load()
        has_alpha = normalized.mode in {"RGBA", "LA"} or (
            normalized.mode == "P" and "transparency" in normalized.info
        )
        normalized = normalized.convert("RGBA" if has_alpha else "RGB")
        display = _webp(normalized, DISPLAY_MAX_EDGE, 78)
        thumbnail = _webp(normalized, THUMB_MAX_EDGE, 74)

    return PreparedPhoto(source, content_type, display, thumbnail)


def prepare_avatar(source: bytes) -> PreparedAvatar:
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("source avatar must be between 1 byte and 25 MiB")

    with Image.open(BytesIO(source)) as opened:
        content_type = _CONTENT_TYPES.get(opened.format or "")
        if content_type is None:
            raise ValueError("legacy avatar must be JPEG/MPO, PNG, or WebP")
        normalized = ImageOps.exif_transpose(opened)
        normalized.load()
        has_alpha = normalized.mode in {"RGBA", "LA"} or (
            normalized.mode == "P" and "transparency" in normalized.info
        )
        normalized = normalized.convert("RGBA" if has_alpha else "RGB")
        avatar = _webp(normalized, AVATAR_MAX_EDGE, 80)

    return PreparedAvatar(source, content_type, avatar)


def public_url(supabase_url: str, path: str, prefix: str = _PUBLIC_PREFIX) -> str:
    return f"{supabase_url.rstrip('/')}{prefix}{quote(path, safe='/')}"


def apply_candidate(
    candidate: PhotoCandidate,
    source: bytes,
    supabase_url: str,
    upload: Callable[[str, bytes, str], None],
    replace_url: Callable[[PhotoCandidate, str], None],
) -> str:
    prepared = prepare_photo(source)
    objects = (
        ("original", prepared.original, prepared.original_content_type),
        ("display.webp", prepared.display, "image/webp"),
        ("thumb.webp", prepared.thumbnail, "image/webp"),
    )
    for name, body, content_type in objects:
        upload(f"{candidate.target_folder}/{name}", body, content_type)

    display_url = public_url(supabase_url, f"{candidate.target_folder}/display.webp")
    replace_url(candidate, display_url)
    return display_url


def _rows(client: Client, limit: int) -> list[dict]:
    return (
        client.table(TABLE)
        .select("id,user_id,image_url,created_at")
        .not_.is_("image_url", "null")
        .order("created_at")
        .limit(limit)
        .execute()
        .data
        or []
    )


def _avatar_rows(client: Client, limit: int) -> list[dict]:
    return (
        client.table(AVATAR_TABLE)
        .select("user_id,avatar_url")
        .not_.is_("avatar_url", "null")
        .order("user_id")
        .limit(limit)
        .execute()
        .data
        or []
    )


def _apply(client: Client, supabase_url: str, candidates: list[PhotoCandidate]) -> None:
    bucket = client.storage.from_(BUCKET)

    def upload(path: str, body: bytes, content_type: str) -> None:
        bucket.upload(
            path,
            body,
            {
                "content-type": content_type,
                "cache-control": "31536000",
                "upsert": "true",
            },
        )

    def replace_url(candidate: PhotoCandidate, display_url: str) -> None:
        response = (
            client.table(TABLE)
            .update({"image_url": display_url})
            .eq("id", candidate.comment_id)
            .eq("image_url", candidate.old_url)
            .execute()
        )
        if len(response.data or []) != 1:
            raise RuntimeError(f"comment {candidate.comment_id} changed during backfill")

    for index, candidate in enumerate(candidates, start=1):
        source = bucket.download(candidate.source_path)
        display_url = apply_candidate(candidate, source, supabase_url, upload, replace_url)
        print(f"[{index}/{len(candidates)}] updated {candidate.comment_id} -> {display_url}")


def apply_avatar_candidate(
    candidate: AvatarCandidate,
    source: bytes,
    supabase_url: str,
    upload: Callable[[str, bytes, str], None],
    replace_url: Callable[[AvatarCandidate, str], None],
) -> str:
    prepared = prepare_avatar(source)
    for name, body, content_type in (
        ("original", prepared.original, prepared.original_content_type),
        ("avatar.webp", prepared.avatar, "image/webp"),
    ):
        upload(f"{candidate.target_folder}/{name}", body, content_type)

    avatar_url = public_url(
        supabase_url,
        f"{candidate.target_folder}/avatar.webp",
        _AVATAR_PUBLIC_PREFIX,
    )
    replace_url(candidate, avatar_url)
    return avatar_url


def _apply_avatars(client: Client, supabase_url: str, candidates: list[AvatarCandidate]) -> None:
    bucket = client.storage.from_(AVATAR_BUCKET)

    def upload(path: str, body: bytes, content_type: str) -> None:
        bucket.upload(
            path,
            body,
            {
                "content-type": content_type,
                "cache-control": "31536000",
                "upsert": "true",
            },
        )

    def replace_url(candidate: AvatarCandidate, avatar_url: str) -> None:
        response = (
            client.table(AVATAR_TABLE)
            .update({"avatar_url": avatar_url})
            .eq("user_id", candidate.user_id)
            .eq("avatar_url", candidate.old_url)
            .execute()
        )
        if len(response.data or []) != 1:
            raise RuntimeError(f"profile {candidate.user_id} changed during backfill")

    for index, candidate in enumerate(candidates, start=1):
        source = bucket.download(candidate.source_path)
        avatar_url = apply_avatar_candidate(candidate, source, supabase_url, upload, replace_url)
        print(f"[{index}/{len(candidates)}] updated {candidate.user_id} -> {avatar_url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write variants and update source rows")
    parser.add_argument("--target", choices=("comments", "avatars"), default="comments")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")

    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not service_key:
        parser.error("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")

    client = create_client(supabase_url, service_key)
    if args.target == "avatars":
        candidates = find_avatar_candidates(_avatar_rows(client, args.limit), supabase_url)
    else:
        candidates = find_candidates(_rows(client, args.limit), supabase_url)
    mode = "apply" if args.apply else "dry-run"
    print(f"{mode}: {len(candidates)} legacy {args.target} eligible")
    for candidate in candidates:
        item_id = getattr(candidate, "comment_id", candidate.user_id)
        print(f"- {item_id}: {candidate.source_path}")
    if args.apply:
        if args.target == "avatars":
            _apply_avatars(client, supabase_url, candidates)
        else:
            _apply(client, supabase_url, candidates)
        print(f"complete: updated {len(candidates)} {args.target}; legacy objects were not deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
