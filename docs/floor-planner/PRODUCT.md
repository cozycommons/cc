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

## Agent editing

1. A user connects an MCP client to the shared Cozy Commons server through browser sign-in with their existing
   Cozy Commons account and explicitly approves the connection. The agent can
   read accessible plans and edit plans owned by that user or shared with them.
   Knowing a private plan ID does not grant access.
2. The agent can inspect the drawing schema and read a plan's current scene and
   revision. Coordinates and dimensions use inches; rotation uses degrees.
3. The agent submits a batch of up to 100 element additions, updates, or
   deletions with the revision it read. A valid batch saves as one change;
   invalid geometry, missing IDs, duplicate IDs, and stale revisions leave the
   stored scene unchanged. After a conflict the agent must read the plan again.
4. Agent tools cannot change ownership, sharing, visibility, or delete a plan.
   Shape edits preserve source notes, rooms, and the browser's saved viewport.
5. Existing browser conflict recovery applies when a person and agent edit at
   the same time. Browser undo is local editing history, not a history of
   remote agent changes.

## Scan viewing

1. Owners and invited editors can attach one USDZ scan to a plan, replace it,
   or remove it. The 3D scan tab supports orbit, pan, zoom, and fit. The scan is
   a reference; viewing it does not convert it into editable shapes.
2. Scans remain accessible only to the owner and invited editors, including
   when the 2D plan is public. Changing 2D visibility does not publish a scan.
3. Uploads accept self-contained USDZ files up to 50 MiB. Loading, upload, and
   rendering errors offer a retry; failed replacement keeps the previous scan.
   A concurrent replacement or revoked edit permission rejects the change.
4. Switching between 2D and 3D preserves the drawing and local recovery draft.
   Removing a scan does not remove drawing elements.

See [SCANS.md](SCANS.md) for scan compatibility, limits, and deployment setup.
