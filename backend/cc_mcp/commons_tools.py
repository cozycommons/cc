"""Sign-in-only project discovery; projects can add account status callbacks."""
from dataclasses import dataclass
from typing import Callable
import logging

from starlette.concurrency import run_in_threadpool
from cc_mcp.server import ToolProvider
from trips.profiles import current_profile

logger = logging.getLogger(__name__)


def trips_status(client, user):
    response = (client.table('trips_groups').select('id', count='exact', head=True)
                .contains('member_user_ids', [user.id]).execute())
    return {'trip_count': response.count, 'setup': bool(response.count),
            'next_step': 'Call get_trip_overview.' if response.count else 'Create a trip at https://cozycommons.dev/trips.'}


def plans_status(client, user):
    owned = (client.table('floor_plan_documents').select('id', count='exact', head=True)
             .eq('owner_id', str(user.id)).execute()).count
    shared = (client.table('floor_plan_invitations').select('document_id', count='exact', head=True)
              .eq('accepted_user_id', str(user.id)).is_('revoked_at', 'null').execute()).count
    return {'has_plans': bool(owned or shared), 'setup': bool(owned or shared),
            'next_step': 'Call list_floor_plans.' if owned or shared else 'Create a plan or accept an invitation at https://cozycommons.dev/floor-planner.'}


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    description: str
    url: str
    on_connector: bool = False
    status: Callable | None = None
    separate_endpoint: str | None = None


# Registry is the M3 extension point: attach a cheap, read-only status callback per project.
PROJECTS = (
    Project('trips', 'Cozy Trips', 'Shared trip expenses, balances and repayments.',
            'https://cozycommons.dev/trips', True, trips_status),
    Project('floor-planner', 'Floor Planner', 'Measured room plans shared by email.',
            'https://cozycommons.dev/floor-planner', True, plans_status),
    Project('dice', 'Dice', 'Beer die records, rankings and stats.', 'https://cozycommons.dev/dice'),
    Project('beli', 'Beli', 'Save restaurant recommendations from Instagram.',
            'https://api.cozycommons.dev/beli/mcp', separate_endpoint='/beli/mcp'),
    Project('resy', 'Resy', 'Find and book restaurant reservations.',
            'https://api.cozycommons.dev/resy/mcp', separate_endpoint='/resy/mcp'),
    Project('partiful', 'Partiful', 'Manage events and invitations.',
            'https://api.cozycommons.dev/partiful/mcp', separate_endpoint='/partiful/mcp'),
    Project('espn', 'ESPN', 'Manage fantasy league data and lineups.',
            'https://api.cozycommons.dev/espn/mcp', separate_endpoint='/espn/mcp'),
    Project('fantasy', 'Fantasy', 'Fantasy basketball predictions updated daily.', 'https://cozycommons.dev/fantasy'),
    Project('crowdset', 'Crowdset', 'Collect and watch shared concert videos.', 'https://cozycommons.dev/crowdset'),
    Project('design', 'Design gallery', 'Browse Cozy Commons interface design studies.', 'https://cozycommons.dev/design'),
)


def project_status(client, user):
    results = []
    for project in PROJECTS:
        status = {'setup': 'unknown', 'next_step': f'Open {project.url}.'}
        if project.separate_endpoint:
            status.update(setup='available via separate endpoint, coming to this connector',
                          next_step=f'Connect {project.url} and use the project’s existing api_token onboarding.')
        if project.status:
            try:
                status = project.status(client, user)
            except Exception:
                logger.warning('Project setup status unavailable: %s', project.id)
                status['next_step'] = f'Status unavailable; open {project.url} to check your setup.'
        results.append({'id': project.id, 'name': project.name, 'description': project.description,
                        'url': project.url, 'on_connector': project.on_connector, 'status': status})
    return {'projects': results}


def register_tools(mcp, context):
    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def whoami() -> dict:
        """Return your signed-in Commons user ID, email and display name."""
        user = await context.signed_in_user(context.need_scope())
        profile = await run_in_threadpool(current_profile, context.service_client, user)
        return {'id': user.id, 'email': user.email, 'display_name': profile['display_name']}

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    async def list_projects() -> dict:
        """Call first: discover Commons projects, available tools and account setup steps."""
        user = await context.signed_in_user(context.need_scope())
        return await run_in_threadpool(project_status, context.service_client, user)


provider = ToolProvider('commons', (), register_tools)
