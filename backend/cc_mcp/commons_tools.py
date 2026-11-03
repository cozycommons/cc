"""Sign-in-only discovery and per-user project enablement on the shared connector."""
from dataclasses import dataclass
import logging

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_context
from starlette.concurrency import run_in_threadpool

from cc_mcp import projects
from cc_mcp.server import COMMONS, ToolProvider
from trips.profiles import current_profile

logger = logging.getLogger(__name__)

REFRESH_NOTE = ('Sent notifications/tools/list_changed. If the tools do not appear, refresh the tool list '
                'or reconnect the connector; the setting is already saved.')


@dataclass(frozen=True)
class CatalogProject:
    """A Commons project without tools on this connector yet."""
    id: str
    name: str
    description: str
    url: str
    separate_endpoint: str | None = None


CATALOG = (
    CatalogProject('dice', 'Dice', 'Beer die records, rankings and stats.', 'https://cozycommons.dev/dice'),
    CatalogProject('partiful', 'Partiful', 'Manage events and invitations.',
                   'https://api.cozycommons.dev/partiful/mcp', '/partiful/mcp'),
    CatalogProject('espn', 'ESPN', 'Manage fantasy league data and lineups.',
                   'https://api.cozycommons.dev/espn/mcp', '/espn/mcp'),
    CatalogProject('fantasy', 'Fantasy', 'Fantasy basketball predictions updated daily.', 'https://cozycommons.dev/fantasy'),
    CatalogProject('crowdset', 'Crowdset', 'Collect and watch shared concert videos.', 'https://cozycommons.dev/crowdset'),
    CatalogProject('design', 'Design gallery', 'Browse Cozy Commons interface design studies.', 'https://cozycommons.dev/design'),
)


def next_step(provider, state):
    status = state['status'] or {}
    if not state['enabled']:
        return f"Call enable_project('{provider.name}') to add its {len(provider.tools)} tools."
    if state['linked'] is False:
        return provider.link.instructions
    return status.get('next_step') or f'Use the {provider.display_name} tools.'


def catalog_entry(project):
    if project.separate_endpoint:
        status = {'setup': 'available via separate endpoint, coming to this connector',
                  'next_step': f'Connect {project.url} and use the project’s existing api_token onboarding.'}
    else:
        status = {'setup': 'unknown', 'next_step': f'Open {project.url}.'}
    return {'id': project.id, 'name': project.name, 'description': project.description, 'url': project.url,
            'on_connector': False, 'enabled': False, 'tools': [], 'status': status, 'next_step': status['next_step']}


def project_listing(client, user, providers):
    states = projects.project_states(client, user, providers)
    results = []
    for provider in providers:
        state = states[provider.name]
        results.append({'id': provider.name, 'name': provider.display_name, 'description': provider.description,
                        'url': provider.url, 'on_connector': True, 'enabled': state['enabled'],
                        'enabled_reason': state['source'], 'linked': state['linked'],
                        'tools': [{'name': name, 'access': level} for name, level in provider.tools.items()],
                        'status': state['status'], 'next_step': next_step(provider, state)})
    return {'projects': results + [catalog_entry(project) for project in CATALOG]}


async def notify_tools_changed():
    """Best effort on the current response stream; the connector is stateless HTTP."""
    try:
        context = get_context()
        await context.session.send_notification(
            mt.ServerNotification(mt.ToolListChangedNotification(method='notifications/tools/list_changed')),
            related_request_id=context.request_id)
    except Exception:
        logger.info('Tool list change notification not delivered')


def register_tools(mcp, context):
    def project(project_id):
        provider = context.provider(project_id)
        if provider and provider.name != COMMONS:
            return provider
        known = next((p for p in CATALOG if p.id == project_id), None)
        if known and known.separate_endpoint:
            raise ToolError(f'{known.name} is not on this connector yet. Use {known.url} with its api_token for now.')
        if known:
            raise ToolError(f'{known.name} has no agent tools yet. Open {known.url}.')
        ids = ', '.join(p.name for p in context.providers if p.name != COMMONS)
        raise ToolError(f"Unknown project '{project_id}'. Use one of: {ids}. Call list_projects for details.")

    async def user():
        return await context.signed_in_user(context.need_scope())

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def whoami() -> dict:
        """Return your signed-in Commons user ID, email and display name."""
        signed_in = await user()
        profile = await run_in_threadpool(current_profile, context.service_client, signed_in)
        return {'id': signed_in.id, 'email': signed_in.email, 'display_name': profile['display_name']}

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def list_projects() -> dict:
        """Call first: each project, whether it is enabled for you, its tools and your exact next step."""
        signed_in = await user()
        providers = [p for p in context.providers if p.name != COMMONS]
        return await run_in_threadpool(project_listing, context.service_client, signed_in, providers)

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': False})
    async def enable_project(project_id: str) -> dict:
        """Add a project's tools to this connector for you, and return them with any one-time setup step."""
        signed_in = await user()
        provider = project(project_id)
        await run_in_threadpool(projects.set_enabled, context.service_client, signed_in.id, provider.name, True)
        state = (await run_in_threadpool(projects.project_states, context.service_client, signed_in, [provider]))[provider.name]
        tools = await mcp.get_tools()
        await notify_tools_changed()
        return {'project_id': provider.name, 'enabled': True, 'linked': state['linked'],
                'tools': [{'name': name, 'access': level, 'description': tools[name].description}
                          for name, level in provider.tools.items()],
                'next_step': next_step(provider, state), 'tool_list': REFRESH_NOTE}

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True,
                           'openWorldHint': False})
    async def disable_project(project_id: str) -> dict:
        """Remove a project's tools from this connector for you. Its data and any linked account are kept."""
        signed_in = await user()
        provider = project(project_id)
        await run_in_threadpool(projects.set_enabled, context.service_client, signed_in.id, provider.name, False)
        await notify_tools_changed()
        return {'project_id': provider.name, 'enabled': False,
                'next_step': f"Call enable_project('{provider.name}') to add its tools again.",
                'tool_list': REFRESH_NOTE}


provider = ToolProvider(COMMONS, register_tools,
                        {'whoami': 'signin', 'list_projects': 'signin',
                         'enable_project': 'signin', 'disable_project': 'signin'},
                        title='Cozy Commons', description='Account, project discovery and project enablement.',
                        url='https://cozycommons.dev/connect')
