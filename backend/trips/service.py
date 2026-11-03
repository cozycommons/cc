"""Shared persistence boundary for REST and agent ledger commands."""
from .ledger import LedgerError


def read_row(client, trip_id):
    rows = client.table('trips_groups').select('*').eq('id', str(trip_id)).execute().data
    if not rows:
        raise LedgerError('Trip not found or you are not a member.', 404)
    return rows[0]


def save_revision(client, before, after):
    rows = (client.table('trips_groups')
            .update({key: after[key] for key in ['data', 'member_user_ids', 'revision', 'updated_at']})
            .eq('id', before['id']).eq('revision', before['revision']).execute().data)
    if not rows:
        raise LedgerError('Someone changed this trip. Refresh, review the changes, and try again.', 409)
    return rows[0]
