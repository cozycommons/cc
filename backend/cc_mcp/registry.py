"""Every provider served at /mcp. Add a project here; the safety tests cover it."""
from cc_mcp.commons_tools import provider as commons
from floor_planner.agent_tools import provider as floor_planner
from ig_logger.sinks.beli.agent_tools import provider as beli
from resy.agent_tools import provider as resy
from trips.agent_tools import provider as trips

PROVIDERS = (commons, trips, floor_planner, beli, resy)
