# Floor Planner

Floor Planner lets Cozy Commons users sketch measured apartment layouts and
share them with people who can help edit. It is available from the Cozy Commons
projects page at `/floor-planner`.

## Plans and access

The library has **My plans**, **Shared with me**, and **Public gallery**. A
signed-in user can start with a blank canvas or the supplied measured-apartment
layout. New plans are private. Owners can rename, delete, or make a plan public.

Anyone can open a public plan and pan or zoom it in read-only mode. Public plans
appear in the gallery without exposing the owner's identity or invitation
addresses. Invited people can edit the drawing after they sign in with the
invited, verified email address. An invitation can be added before that person
has a Cozy Commons account; it becomes usable when that email is verified in
Supabase Auth. An owner can copy a plan link, add invitees, and remove edit
access. Cozy Commons does not send invitation emails automatically.

Ownership is fixed when a plan is created. Only the owner can change its name,
visibility, or invitations, and can delete it. All invited editors can change
the drawing. A public viewer cannot save edits.

## Editing and recovery

The editor uses inches and provides wall, door-gap, window, rectangle, ellipse,
line, freehand, and furniture tools. It supports selection, measurements,
2-inch snapping, pan and zoom, fit, undo, redo, and reset to the original blank
or apartment starting point.

Changes save automatically. If another editor saves first, the local draft is
kept and the editor offers a reload of the latest plan. If access is removed or
a save fails, the editor keeps the local draft available for recovery. Drafts
are scoped to the signed-in user and plan. Read-only viewing does not save or
cache a private scene in local storage.
