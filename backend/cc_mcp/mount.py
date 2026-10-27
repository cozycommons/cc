"""Mount the shared MCP app after all explicit API routes."""


def mount_agent_app(app, agent_app):
    app.mount("/", agent_app)
