from io import BytesIO

from PIL import Image
import pytest

from dice.photo_backfill import (
    AVATAR_MAX_EDGE,
    DISPLAY_MAX_EDGE,
    THUMB_MAX_EDGE,
    apply_avatar_candidate,
    apply_candidate,
    avatar_candidate_from_row,
    candidate_from_row,
    find_avatar_candidates,
    find_candidates,
    prepare_avatar,
    prepare_photo,
)


SUPABASE_URL = "https://project.supabase.co"
COMMENT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
LEGACY_URL = (
    f"{SUPABASE_URL}/storage/v1/object/public/dice-comment-photos/"
    f"{USER_ID}/old%20photo.jpg"
)
LEGACY_AVATAR_URL = (
    f"{SUPABASE_URL}/storage/v1/object/public/dice-profile-photos/"
    f"{USER_ID}/old%20avatar.jpg"
)


def _row(image_url=LEGACY_URL):
    return {"id": COMMENT_ID, "user_id": USER_ID, "image_url": image_url}


def _profile(avatar_url=LEGACY_AVATAR_URL):
    return {"user_id": USER_ID, "avatar_url": avatar_url}


def _jpeg(width=2400, height=1200):
    output = BytesIO()
    Image.new("RGB", (width, height), "#6b4eff").save(output, format="JPEG", quality=95)
    return output.getvalue()


def _mpo():
    output = BytesIO()
    first = Image.new("RGB", (1200, 800), "#6b4eff")
    second = Image.new("RGB", (1200, 800), "#111827")
    first.save(output, format="MPO", save_all=True, append_images=[second])
    return output.getvalue()


def test_candidate_accepts_only_owned_legacy_storage_urls():
    candidate = candidate_from_row(_row(), SUPABASE_URL)
    assert candidate.source_path == f"{USER_ID}/old photo.jpg"
    assert candidate.target_folder == f"{USER_ID}/backfill-{COMMENT_ID}"

    assert candidate_from_row(_row(f"{SUPABASE_URL}/x/display.webp"), SUPABASE_URL) is None
    with pytest.raises(ValueError, match="external image URL"):
        candidate_from_row(_row("https://example.com/photo.jpg"), SUPABASE_URL)
    with pytest.raises(ValueError, match="unsafe storage path"):
        candidate_from_row(_row(f"{SUPABASE_URL}/storage/v1/object/public/dice-comment-photos/a/../b.jpg"), SUPABASE_URL)


def test_find_candidates_skips_already_compacted_photos():
    compact = (
        f"{SUPABASE_URL}/storage/v1/object/public/dice-comment-photos/"
        f"{USER_ID}/new/display.webp"
    )
    assert find_candidates([_row(compact), _row()], SUPABASE_URL) == [
        candidate_from_row(_row(), SUPABASE_URL)
    ]


def test_avatar_candidates_only_include_owned_legacy_storage_objects():
    candidate = avatar_candidate_from_row(_profile(), SUPABASE_URL)
    assert candidate.source_path == f"{USER_ID}/old avatar.jpg"
    assert candidate.target_folder.startswith(f"{USER_ID}/backfill-")

    compact = (
        f"{SUPABASE_URL}/storage/v1/object/public/dice-profile-photos/"
        f"{USER_ID}/new/avatar.webp"
    )
    assert find_avatar_candidates([
        _profile(compact),
        _profile("https://lh3.googleusercontent.com/avatar=s96-c"),
        _profile("/dice/demo-avatars/alpha/avatar.webp"),
        _profile(),
    ], SUPABASE_URL) == [candidate]

    with pytest.raises(ValueError, match="unsafe storage path"):
        avatar_candidate_from_row(
            _profile(
                f"{SUPABASE_URL}/storage/v1/object/public/dice-profile-photos/a/../b.jpg"
            ),
            SUPABASE_URL,
        )


def test_prepare_photo_preserves_original_and_bounds_webp_variants():
    original = _jpeg()
    prepared = prepare_photo(original)
    assert prepared.original == original
    assert prepared.original_content_type == "image/jpeg"

    for body, max_edge in (
        (prepared.display, DISPLAY_MAX_EDGE),
        (prepared.thumbnail, THUMB_MAX_EDGE),
    ):
        with Image.open(BytesIO(body)) as image:
            assert image.format == "WEBP"
            assert max(image.size) <= max_edge


def test_prepare_photo_accepts_iphone_mpo_as_a_jpeg_original():
    original = _mpo()
    prepared = prepare_photo(original)
    assert prepared.original == original
    assert prepared.original_content_type == "image/jpeg"
    with Image.open(BytesIO(prepared.thumbnail)) as thumbnail:
        assert thumbnail.format == "WEBP"
        assert max(thumbnail.size) <= THUMB_MAX_EDGE


def test_prepare_avatar_preserves_original_and_bounds_webp():
    original = _jpeg()
    prepared = prepare_avatar(original)
    assert prepared.original == original
    assert prepared.original_content_type == "image/jpeg"
    with Image.open(BytesIO(prepared.avatar)) as avatar:
        assert avatar.format == "WEBP"
        assert max(avatar.size) <= AVATAR_MAX_EDGE


def test_apply_uploads_all_objects_before_conditionally_replacing_url():
    candidate = candidate_from_row(_row(), SUPABASE_URL)
    calls = []

    def upload(path, body, content_type):
        calls.append(("upload", path, content_type, body))

    def replace_url(value, display_url):
        calls.append(("replace", value.old_url, display_url))

    display_url = apply_candidate(candidate, _jpeg(800, 600), SUPABASE_URL, upload, replace_url)
    paths = [call[1] for call in calls[:3]]
    assert paths == [
        f"{candidate.target_folder}/original",
        f"{candidate.target_folder}/display.webp",
        f"{candidate.target_folder}/thumb.webp",
    ]
    assert calls[0][3] == _jpeg(800, 600)
    assert calls[-1] == ("replace", LEGACY_URL, display_url)
    assert display_url.endswith(f"/{candidate.target_folder}/display.webp")


def test_apply_avatar_uploads_original_before_compact_url_replacement():
    candidate = avatar_candidate_from_row(_profile(), SUPABASE_URL)
    calls = []

    def upload(path, body, content_type):
        calls.append(("upload", path, content_type, body))

    def replace_url(value, avatar_url):
        calls.append(("replace", value.old_url, avatar_url))

    avatar_url = apply_avatar_candidate(
        candidate,
        _jpeg(800, 600),
        SUPABASE_URL,
        upload,
        replace_url,
    )
    assert [call[1] for call in calls[:2]] == [
        f"{candidate.target_folder}/original",
        f"{candidate.target_folder}/avatar.webp",
    ]
    assert calls[0][3] == _jpeg(800, 600)
    assert calls[-1] == ("replace", LEGACY_AVATAR_URL, avatar_url)
    assert avatar_url.endswith(f"/{candidate.target_folder}/avatar.webp")
