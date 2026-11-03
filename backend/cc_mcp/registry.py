"""Every provider served at /mcp. Add a project here; the safety tests cover it."""
from cc_mcp.commons_tools import provider as commons
from floor_planner.agent_tools import provider as floor_planner
from trips.agent_tools import provider as trips

PROVIDERS = (commons, trips, floor_planner)
