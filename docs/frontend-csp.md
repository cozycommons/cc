# Frontend Content Security Policy

The shared nginx frontend enforces CSP immediately. Production route loads and
synthetic credential/OAuth flows are checked under nginx before opening the PR;
Report-Only would leave password exfiltration channels open. This policy applies
to `frontend/Dockerfile`, not the separate Crowdset Python static-file server or
the legacy `jasonkeung.com` deployment.

## Production origin inventory

The inventory comes from the shipped React sources, imported design CSS, and
backend response contracts. Deployment-specific hosts come from build arguments,
not a wildcard Supabase project or an independent runtime allowlist.

| Resource | Destination and reason |
| --- | --- |
| Scripts, lazy chunks, icons, design assets, manifests | Same origin, Vite bundles and `public/`. No CDN scripts, inline scripts, eval, workers or frames. |
| Shared API and analytics | `VITE_API_URL`, including `/track/events` and `/track/pageview`. Analytics has no external collector. |
| Supabase | `VITE_SUPABASE_URL` under `/auth/v1/`, `/rest/v1/`, `/storage/v1/`; corresponding `wss:` origin under `/realtime/v1/`. Supabase JS owns the auth, REST, storage and realtime clients. |
| Fonts | Google CSS at `https://fonts.googleapis.com/css2`, files at `https://fonts.gstatic.com/s/`. Dice, Floor Planner and Dice design CSS import these. Credential pages use local/system fonts. |
| Images | Same origin, data URLs for CSS grain/embedded logos, blob URLs for image processing and scan textures, Supabase storage, Google account photos (`lh3.googleusercontent.com`), ESPN (`a.espncdn.com`, `g.espncdn.com`), user-provided HTTPS avatars and Venmo photos. General pages retain `https:` images because profile APIs accept arbitrary image hosts. |
| Fantasy fallback | `https://gist.githubusercontent.com/homatthew/a417a860db31c1a9e5c13b08338b7a65/raw/` when API predictions are absent. No other gist accounts are allowed. |
| Crowdset | API and media entry URLs are same origin. Remote media, thumbnail and preview responses redirect to signed R2 URLs; multipart PUTs also use signed R2 URLs. If hosted through this nginx image, set optional `VITE_CSP_CROWDSET_UPLOAD_ORIGIN` to that exact R2 account origin at build time, for connections and media playback. No R2 wildcard is allowed. Current separate Crowdset hosting does not use this nginx configuration. YouTube imports run on the server, without browser YouTube embeds. |
| Floor Planner / 3D | Bundled Three.js; scan bytes from the API and archive-contained texture bytes. No remote model/CDN/decoder origins. External scan textures are already rejected by the parser. |
| OAuth and outgoing links | Google sign-in navigates to Supabase authorization, then Google; consent approves/denies via Supabase auth and navigates to its validated callback. No iframe or form POST is involved. ESPN, Venmo, connector setup and support links are ordinary navigations, not fetch destinations. |

## Credential documents

`/account` and `/oauth/consent` use a stricter policy, including case variants,
trailing slashes and encoded path segments. nginx selects using its decoded,
normalized original URI before serving `index.html`. Named SPA fallback preserves
that selection; cache headers and CSP are both retained on 200/304/error responses.

Credential documents allow connections only to the exact configured API's
`/account` and `/account/` subtree, and Supabase auth/storage. They omit analytics,
REST, realtime, gist, R2, external CSS/fonts, media and arbitrary HTTPS images.
Their images allow local/data/blob images, the configured Supabase storage path,
and Google account photos. Other custom profile photos render the existing
local generated avatar on these pages. Uploading a replacement still works.
Inline styles remain necessary for React layout and generated avatars.

The React boundary reloads the document before mounting content when navigation
crosses between general and credential pages, including history navigation.
Query strings and hashes are retained. This matters because `pushState` does
not fetch a new CSP header. Leaving the credential pages reloads too, restoring
permissions needed by the destination route.

`form-action 'none'` is intentional: all legitimate forms prevent native submit
and send fetch requests. `base-uri 'none'`, `object-src 'none'`, `frame-src 'none'`
and `frame-ancestors 'none'` apply throughout. The build rejects unsafe service URL
syntax before inserting values into nginx configuration. HTTPS is required,
except explicit loopback HTTP for local tests.

## Scope and limits

CSP restricts browser resource and network sinks; it does not make a compromised
first-party bundle trustworthy. Code can still use allowed account/auth/storage
endpoints, read same-origin browser state, or navigate the top-level window.
`connect-src` does not constrain top-level navigation, and OAuth needs external
navigation. CSP also cannot distinguish allowed requests by HTTP method or body.
Server authorization, credential handling and dependency integrity remain
necessary. A stronger boundary against malicious first-party code would require
isolating credential entry from the main application's origin and bundles.

Build configuration changes require a rebuild so the policy and browser URLs
remain synchronized. The generated `dist/nginx.conf` is copied into nginx's
template directory and removed from the image's public asset directory.

## Local verification

Use synthetic HTTPS service names to avoid production calls. Build with
`VITE_API_URL=https://api.example.test`,
`VITE_SUPABASE_URL=https://auth.example.test`, and a placeholder publishable key.
Serve `frontend/dist` with `nginx:stable-alpine`, mounting the generated
`dist/nginx.conf` at `/etc/nginx/templates/default.conf.template` and substituting
only `$PORT`, as the Dockerfile does. Use a loopback published port, such as
`127.0.0.1:8096:80`. On Colima, keep bind-mount sources beneath `$HOME`.

Run `frontend/e2e/csp.mjs` with Node from the repository root.
`CSP_QA_URL` defaults to `http://127.0.0.1:8096` and rejects non-loopback hosts.
`CSP_QA_MODULES` can point to a temporary package.json with Playwright installed;
the harness uses the locally installed Chrome in headless mode. Results are
written to ignored `artifacts/csp/browser-results.json`.

The harness forwards synthetic HTTPS document/asset requests to actual nginx,
preserving response headers, and stubs only API/auth/image/callback responses.
Google font requests remain real. It checks all top-level routes signed out
and signed in, credential path variants, Beli submit, OAuth approve/deny,
React Link and back/forward reloads, built Three.js USDZ rendering, blob images,
and blocked network/beacon/script/eval/image/frame/form probes. It never uses
real linked-account credentials or a production API/database.

The policy follows [CSP fetch directive behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy)
and [nginx header inheritance](https://nginx.org/en/docs/http/ngx_http_headers_module.html).
The explicit websocket source follows [Supabase's realtime endpoint](https://supabase.com/docs/guides/realtime/protocol).
