# Attached apartment scans

## Confirmed scope

Attach an existing USDZ apartment scan to a Floor Planner plan and view it in
the browser with orbit, pan, zoom, and fit controls. Preserve the 2D scene;
this feature does not derive editable walls or generate a new 3D model.
The supplied apartment USDZ was validated and rendered locally, including
orbit, zoom, and fit. The private file and its screenshots are not repository
fixtures. Synthetic fixtures provide repeatable automated coverage.

The viewer uses the pinned Three.js `USDLoader`, whose current official
documentation supports both ASCII USDA and binary USDC content inside USDZ:
<https://threejs.org/docs/pages/USDLoader.html>. Loading is deferred until
opening the scan. Server conversion to GLB is unnecessary for the first
version; investigate it only if the actual file exposes unsupported features.
The viewer reuses the loader's official USDA/USDC parsers and composer through
an archive-only adapter. Three.js can assign texture `Image.src` without
consulting `LoadingManager`, so the adapter rejects string/URL texture sources
at composition time and permits embedded image bytes only. Its regression
tests are required when upgrading the pinned Three.js version.

## Visibility

Scans remain accessible only to the owner and active email-invited
editors, even when the associated 2D plan is in the public gallery. The upload
and view controls state this separately. This is the private default for this
version, explicitly confirmed by Jason; publishing a 2D plan does not publish
an apartment scan.

## Accepted technical constraints

- Private storage bucket, authenticated backend byte delivery, and no public
  object URLs. Check current plan permissions on each request.
- One attached USDZ per plan, replaceable and removable by authorized editors.
- At most 50 MiB uploaded, with bounded ZIP entries and uncompressed totals.
  Reject invalid archives, unsupported root layers, path traversal, encrypted
  entries, and references requiring external network requests.
- Loading, upload failure, invalid-model, unavailable-WebGL, and retry states.
- Dispose geometry, materials, textures, controls, observers, and WebGL state
  when closing or replacing a scan. Camera changes never alter saved scenes.

## Validation evidence

Backend unit tests cover archive validation, expansion limits, unsafe paths,
duplicate entries, ASCII/binary root headers, and integrity metadata. The
loopback integration test exercises upload/read/replace/remove, owner and
invitee access, revocation both through HTTP and directly through the atomic
RPC, public-plan separation, Storage denial, conflicts, former-object removal,
and queued cleanup after deleting a plan. The full isolated migration
upgrade/convergence suite passes with the additional Storage scaffold.

Frontend tests cover upload, error handling, unchanged attachments after
failed replacements, account/access loss, loading, retry, fit, and cleanup of
late renderer completion. The official loader parses the synthetic apartment
fixture into seven meshes with the expected finite bounds. Production build,
deferred bundle budgets, and targeted lint pass. Local browser QA uploaded
the synthetic fixture through the file picker and verified rendering, orbit,
zoom, and fit. Subsequent browser checks verified tab remounting, return to
the 2D editor, and sharing after integration. The actual supplied apartment scan also passed archive validation and parsed
into 28 meshes with finite bounds. It contains parametric geometry rather than
embedded photo textures. Its very thin surfaces exposed depth-buffer artifacts;
the viewer uses logarithmic depth to keep nearby wall and opening faces distinct.

Additional compatibility QA uses Three.js r186's official
[`saeukkang.usdz` example](https://github.com/mrdoob/three.js/blob/r186/examples/models/usdz/saeukkang.usdz),
which contains a USDA mesh and embedded PNG. A local QA-only derivative uses
macOS OpenUSD `usdcat` to encode that same mesh as binary USDC while retaining
the PNG. Both the official loader and archive adapter produce identical
geometry bounds, one mesh, 75,000 vertices, and one textured material for both
archives. Those parser comparisons stub image decoding; a separate real-browser
upload of the binary derivative verified actual embedded PNG decoding and
textured WebGL rendering. Official sample downloads and derivatives stay in `/tmp`,
outside source control. A separate tiny synthetic USDC wall is encoded in the
unit-test fixture so binary parser regression checks need no platform tool.

## Operations

Migration `0002_floor_planner_scans.sql` provisions the private
`floor-plan-scans` bucket, metadata and cleanup tables, restrictive browser
Storage denial policy, and service-only atomic attachment RPC. It advances
the feature contract to version 2 without changing the historical migration.
The hosted project's global Storage upload limit must be at least 50 MiB;
the migration sets only the bucket limit. The loopback configuration sets
50 MiB as its global limit. The feature reuses the existing server-only
Supabase service client; no additional credentials are sent to the browser.

Uploading reserves an object cleanup entry before storing bytes. Successful
attachment removes that reservation. Replacing, removing, or deleting a plan
queues the former object, with immediate removal on normal replace/remove
requests. Failed cleanup remains queued. Authorized metadata/upload requests
retry up to ten entries older than one hour, checking that each object is no
longer attached before removing it. With no subsequent requests, queued
cleanup waits until the next authorized scan request. A lost RPC response
does not immediately delete its potentially committed upload.
