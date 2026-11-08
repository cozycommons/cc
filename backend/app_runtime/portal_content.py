"""Public onboarding content for the Cozy Commons Apps portal."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

router = APIRouter()

MCP_ENDPOINT = "https://api.cozycommons.dev/mcp"
OAUTH_METADATA = "https://api.cozycommons.dev/.well-known/oauth-authorization-server"
RESOURCE_METADATA = "https://api.cozycommons.dev/.well-known/oauth-protected-resource/mcp"

AGENT_SETUP = f"""Cozy Commons agent setup

MCP endpoint: {MCP_ENDPOINT}
Transport: Streamable HTTP
Authentication: OAuth authorization code with PKCE and dynamic client registration
OAuth server metadata: {OAUTH_METADATA}
Protected resource metadata: {RESOURCE_METADATA}

If you can configure this user's MCP client, add the endpoint with OAuth and ask
before changing persistent client settings. Otherwise, show the matching manual
steps below. The user must complete browser sign-in and approve consent; never
request or enter their credentials.

Permissions:
- commons:read allows reading data the signed-in user can access.
- commons:edit allows tools to make changes.

Client setup:
- Claude web/Desktop: Customize → Connectors → Add custom connector. Paste the
  endpoint and authorize with OAuth. Team and Enterprise may require an owner to
  add it first; users connect individually.
  https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Claude Code: claude mcp add --transport http cozy-commons {MCP_ENDPOINT}
  Start Claude Code, run /mcp, select cozy-commons, and choose Authenticate.
  Sign in in the browser and review and approve the requested permissions.
  https://code.claude.com/docs/en/mcp
- Codex CLI: codex mcp add cozy-commons --url {MCP_ENDPOINT}
  Then run codex mcp login cozy-commons. Sign in in the browser and review and
  approve the requested permissions.
  https://developers.openai.com/codex/extend/mcp
- ChatGPT web: On Business, Enterprise, or Edu, use Plugins → Add custom MCP
  server, configure OAuth, review the warning, create the plugin, and install it.
  Workspace permissions may require an administrator. Developer Mode is not
  required in the current Plugins flow.
  https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt
  ChatGPT's persistent OAuth renewal compatibility is not confirmed yet.
- Codex desktop: Settings → MCP servers → Add server. Save and restart, then
  choose Authenticate for OAuth.
  https://developers.openai.com/codex/extend/mcp

Never share passwords, sign-in codes, access tokens, or client secrets in agent
chat. Add only the official endpoint above.
"""

LLMS = f"""# Cozy Commons Apps

Public agent onboarding:
- https://apps.cozycommons.dev/connect
- Plain-text setup: https://apps.cozycommons.dev/agent-setup.txt

MCP endpoint: {MCP_ENDPOINT}
Transport: Streamable HTTP
OAuth server metadata: {OAUTH_METADATA}
Protected resource metadata: {RESOURCE_METADATA}
"""


def landing_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Cozy Commons Apps sign-in and agent setup">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="alternate" type="text/plain" href="/llms.txt">
  <title>Apps · Cozy Commons</title>
  <style>
    body { margin: 0; background: #f7f6f1; color: #292b26; font: 16px/1.6 system-ui, sans-serif; }
    main { box-sizing: border-box; max-width: 680px; margin: 64px auto; padding: 0 24px; }
    h1 { margin: 0 0 24px; font-size: 32px; line-height: 1.2; }
    nav { display: flex; flex-wrap: wrap; gap: 20px; }
    a { color: #375c49; text-underline-offset: 3px; }
    @media (max-width: 640px) { main { margin-top: 40px; } }
  </style>
</head>
<body>
  <main>
    <h1>Cozy Commons Apps</h1>
    <nav aria-label="Apps">
      <a href="/connect">Connect an agent</a>
      <a href="/_commons/login">Sign in with Google</a>
    </nav>
  </main>
</body>
</html>"""


@router.get("/connect", response_class=HTMLResponse)
def connect_page():
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Connect an agent to Cozy Commons Apps">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="alternate" type="text/plain" href="/llms.txt">
  <title>Connect an agent · Cozy Commons Apps</title>
  <style>
    body { margin: 0; background: #f7f6f1; color: #292b26; font: 15px/1.6 system-ui, sans-serif; }
    main { box-sizing: border-box; max-width: 760px; margin: 48px auto; padding: 0 24px; }
    h1 { margin: 0 0 24px; font-size: 32px; line-height: 1.2; }
    h2 { margin: 0 0 8px; font-size: 18px; }
    section { padding: 24px 0; border-top: 1px solid #d9d6ce; }
    p { margin: 10px 0; }
    code { overflow-wrap: anywhere; }
    a { color: #375c49; text-underline-offset: 3px; }
    ul { padding-left: 22px; }
    li { margin: 14px 0; }
    @media (max-width: 640px) { main { margin-top: 32px; } }
  </style>
</head>
<body>
  <main>
    <p><a href="/">Apps</a></p>
    <h1>Connect an agent</h1>
    <section>
      <h2>MCP endpoint</h2>
      <p><code>https://api.cozycommons.dev/mcp</code></p>
      <p>Use a remote MCP client that supports Streamable HTTP and OAuth.</p>
    </section>
    <section>
      <h2>Client setup</h2>
      <ul>
        <li>Claude web/Desktop: Customize → Connectors → Add custom connector. Paste the URL and authorize with OAuth. Team and Enterprise may require an owner to add it first. <a href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp">Claude guide</a></li>
        <li>Claude Code: run <code>claude mcp add --transport http cozy-commons https://api.cozycommons.dev/mcp</code>, then start Claude Code and run <code>/mcp</code>. Select <code>cozy-commons</code>, choose Authenticate, then sign in and review the requested permissions in your browser. <a href="https://code.claude.com/docs/en/mcp">Claude Code guide</a></li>
        <li>Codex CLI: run <code>codex mcp add cozy-commons --url https://api.cozycommons.dev/mcp</code>, then <code>codex mcp login cozy-commons</code>. Sign in and review the requested permissions in your browser. <a href="https://developers.openai.com/codex/extend/mcp">Codex guide</a></li>
        <li>Codex desktop: Settings → MCP servers → Add server. Save and restart, then choose Authenticate. Sign in and review the requested permissions in your browser. <a href="https://developers.openai.com/codex/extend/mcp">Codex guide</a></li>
        <li>ChatGPT web: On Business, Enterprise, or Edu, use Plugins → Add custom MCP server, choose OAuth, review the warning, create the plugin, and install it. Workspace permissions may require an administrator; Developer Mode is not required in the current Plugins flow. Persistent OAuth renewal compatibility is not confirmed yet. <a href="https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt">ChatGPT guide</a></li>
      </ul>
      <p>Other clients need Streamable HTTP and OAuth with PKCE and dynamic client registration. <a href="/agent-setup.txt">Plain-text setup guide</a></p>
    </section>
    <section>
      <h2>Sign in and consent</h2>
      <p>When your client opens a browser, sign in to Cozy Commons with Google if prompted. Review the application name and requested permissions on the Cozy Commons consent page. Allow only if you trust the agent and agree to the access; otherwise deny.</p>
      <p><code>commons:read</code> allows reading data you can access. <code>commons:edit</code> allows tools to make changes.</p>
      <p>Never share passwords, sign-in codes, access tokens, or client secrets in agent chat. Add only the official endpoint above.</p>
    </section>
  </main>
</body>
</html>"""


@router.get("/agent-setup.txt", response_class=PlainTextResponse)
def agent_setup():
    return PlainTextResponse(AGENT_SETUP)


@router.get("/llms.txt", response_class=PlainTextResponse)
def llms():
    return PlainTextResponse(LLMS)
