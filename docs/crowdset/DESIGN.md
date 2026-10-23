# Crowdset design decisions

## Jason's design preferences

- Use concise, functional interface copy.
- Avoid marketing slogans, emotional taglines, tutorial-like explanations, and
  labels that merely narrate an obvious interface.
- Let layout, controls, content, and interaction communicate how the UI works.
- Remove unnecessary copy rather than replacing it with another slogan.
- Keep text that conveys necessary information: event metadata, actions,
  permissions, processing states, errors, and contextual missing-footage states.
- Preserve accessible names for controls even when visible explanatory copy is
  removed.

Examples explicitly rejected: "The night, from inside it", "The night so far",
and "Unfilled = missing".

## Current product scope

- Watch-first interface.
- A set is a live performance identified by artist, venue, and a datetime range
  with a timezone.
- Clips are contributed videos belonging to a set.
- Each set has one canonical public cut assembled by server logic. Crowdset
  chooses the angle; viewers do not select angles or versions.
- Require Google sign-in for watching and contributing.
- Any signed-in user can create a set, with a duplicate check before saving.
- No user-authored clip captions, memory text, or comments in the initial scope.
  Contributor attribution remains.
- Voting, private or custom cuts, and editing interfaces are future possibilities,
  not current features.

## MVP boundary

Build one complete loop: Google sign-in, find or create a set, upload clips,
and watch the canonical public cut. Favor finishing this loop over adding screens
or new features.

The initial screens are sign-in, a searchable set list, set creation, the set
page, and clip upload/review. Duplicate detection belongs in creation; empty,
processing, and failed-upload states belong in the existing flow.

Do not add a separate upload library, profiles, social features, saved sets,
notifications, voting, angle selection, custom cuts, or an editing experience
to the MVP.

### Proposed implementation defaults

- Play clips chronologically, with one angle selected by the server for overlaps.
- Keep the selected clip's audio and use simple cuts. Audio mixing and advanced
  reconstruction are not prerequisites for the first usable release.
- Skip missing intervals; show a concise missing-footage state when seeking
  directly into a gap.
- Use capture timestamps where available; keep uncertain clips pending rather
  than silently assigning an invented time.
- Show upload progress and offer retry on failure. Processing clips do not count
  toward playable coverage.

These defaults are proposed implementation constraints, not additional features.
