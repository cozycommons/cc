"""MapleStory Classic telemetry: EXP overlay runs in Cozy Commons.

Phase 1 is the EXP producer: the overlay's per-day log lines (map, level,
class, party size, EXP/mesos totals) shipped from the player's machine and
read back over REST (/telemetry) and MCP (/telemetry/mcp). Later producers
(e.g. the FM watcher) plug into the same account + token model.
"""
