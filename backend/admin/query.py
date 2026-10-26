"""Bounded SELECT execution against an independently provisioned reader login."""
import json
import os
from datetime import datetime
from decimal import Decimal
from time import monotonic
from threading import BoundedSemaphore, Timer
from uuid import UUID
from urllib.parse import urlparse

import psycopg
from fastapi import HTTPException
from pglast import parser

VIEWS = {'events', 'legacy_events', 'users'}
FUNCTIONS = set('count sum avg min max date_trunc generate_series now lower upper length round abs floor ceil extract date_part row_number rank dense_rank lag lead first_value last_value concat nullif'.split())
TYPES = set('text varchar date timestamp timestamptz interval numeric int2 int4 int8 float4 float8 bool uuid'.split())
NODES = set('SelectStmt ResTarget ColumnRef String Integer Float Boolean A_Const A_Star FuncCall A_Expr RangeVar RangeSubselect RangeFunction JoinExpr Alias TypeCast TypeName SortBy WithClause CommonTableExpr WindowDef NullTest BooleanTest BoolExpr CaseExpr CaseWhen CoalesceExpr MinMaxExpr ParamRef SubLink List'.split())
OPERATORS = {'=', '<>', '!=', '<', '>', '<=', '>=', '+', '-', '*', '/', '%', '||', '~~', '!~~', '~~*', '!~~*'}
SLOTS = BoundedSemaphore(4)


def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def strings(value):
    return [node['sval'] for key, node in walk(value) if key == 'String']


def validate_query(source):
    try:
        statements = json.loads(parser.parse_sql_json(source))['stmts']
    except Exception:
        raise HTTPException(422, 'Invalid SQL.')
    if len(statements) != 1 or set(statements[0]['stmt']) != {'SelectStmt'}:
        raise HTTPException(422, 'Use one SELECT statement.')
    tree = statements[0]['stmt']
    def check_relations(value, visible=frozenset()):
        if isinstance(value, list):
            for item in value:
                check_relations(item, visible)
        elif isinstance(value, dict):
            if 'SelectStmt' in value:
                statement = value['SelectStmt']
                clause = statement.get('withClause', {})
                ctes = [entry['CommonTableExpr'] for entry in clause.get('ctes', [])]
                scope = set(visible)
                if clause.get('recursive'):
                    scope.update(cte['ctename'] for cte in ctes)
                for cte in ctes:
                    check_relations(cte['ctequery'], scope)
                    scope.add(cte['ctename'])
                for name, child in statement.items():
                    if name != 'withClause':
                        check_relations(child, scope)
            elif 'RangeVar' in value:
                relation = value['RangeVar']
                approved = not relation.get('catalogname') and (
                    relation.get('schemaname') == 'analytics' and relation['relname'] in VIEWS or
                    not relation.get('schemaname') and relation['relname'] in visible
                )
                if not approved:
                    raise HTTPException(422, 'Use views from the analytics catalog.')
            else:
                for child in value.values():
                    check_relations(child, visible)
    check_relations(tree)
    for key, node in walk(tree):
        if key[:1].isupper() and key not in NODES:
            raise HTTPException(422, f'Unsupported SQL expression: {key}.')
        if key == 'SelectStmt' and any(node.get(field) for field in ('intoClause', 'lockingClause')):
            raise HTTPException(422, 'Read-only SELECT required.')
        if key in ('FuncCall', 'TypeName', 'typeName'):
            name = strings(node.get('funcname' if key == 'FuncCall' else 'names', []))
            allowed = FUNCTIONS if key == 'FuncCall' else TYPES
            if not name or name[-1] not in allowed or len(name) > 2 or (len(name) == 2 and name[0] != 'pg_catalog'):
                raise HTTPException(422, 'Unsupported function or type.')
        if key == 'A_Expr':
            names = strings(node.get('name', []))
            if len(names) != 1 or names[0] not in OPERATORS:
                raise HTTPException(422, 'Unsupported operator.')
        if key == 'ParamRef' and node['number'] not in (1, 2, 3):
            raise HTTPException(422, 'Parameters are $1 start, $2 end, $3 project.')
    return tree


def reader_url(policy=None):
    url = os.getenv('ANALYTICS_DATABASE_URL', '')
    parsed = urlparse(url)
    if not url:
        raise HTTPException(503, 'Analytics connection is not configured.')
    if parsed.scheme not in {'postgres', 'postgresql'} or (parsed.username or '').split('.')[0] != 'commons_analytics_reader':
        raise HTTPException(503, 'Analytics requires its dedicated reader login.')
    if policy and (policy.is_dice_sandbox or policy.is_trips_sandbox):
        port = 54322 if policy.is_dice_sandbox else 55322
        if parsed.hostname not in {'localhost', '127.0.0.1', '::1'} or parsed.port != port:
            raise HTTPException(503, 'Analytics connection must use the owned loopback database.')
    return url


def encode(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, UUID)):
        return str(value)
    return str(value)


def execute_query(source, start_at, end_at, project, policy=None):
    validate_query(source)
    url = reader_url(policy)
    if not SLOTS.acquire(blocking=False):
        raise HTTPException(429, 'Too many queries. Retry shortly.')
    try:
        with psycopg.connect(url, connect_timeout=3, options='-c default_transaction_read_only=on') as connection:
            connection.execute('SET TRANSACTION READ ONLY')
            role = connection.execute('SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=current_user').fetchone()
            if not role or any(role):
                raise HTTPException(503, 'Analytics reader privileges are invalid.')
            started = monotonic()
            def cancel_query():
                try:
                    connection.cancel()
                except psycopg.Error:
                    pass
            deadline = Timer(10, cancel_query)
            deadline.daemon = True
            deadline.start()
            connection.execute("SET LOCAL statement_timeout = '5s'")
            connection.execute("SET LOCAL lock_timeout = '1s'")
            connection.execute("SET LOCAL search_path = pg_catalog, analytics")
            connection.execute("SET LOCAL timezone = 'UTC'")
            # Render only parser-recognized parameters, never text inside strings/comments.
            from pglast import parse_sql
            from pglast.visitors import Visitor
            from pglast.stream import RawStream
            bindings = (start_at, end_at, project)
            class Bind(Visitor):
                def visit_ParamRef(self, ancestors, node):
                    from pglast import ast
                    value = bindings[node.number - 1]
                    return ast.A_Const(isnull=True) if value is None else ast.A_Const(val=ast.String(sval=str(value)))
            statement = parse_sql(source)
            Bind()(statement)
            rendered = RawStream()(statement)
            with connection.cursor(name='analytics_result') as cursor:
                cursor.execute(rendered)
                columns = [item.name for item in cursor.description]
                if len(columns) > 50 or len(set(columns)) != len(columns):
                    raise HTTPException(422, 'Use at most 50 uniquely named columns.')
                rows, size, truncated = [], 0, False
                for values in cursor:
                    if monotonic() - started >= 10:
                        raise HTTPException(408, 'Query exceeded ten seconds.')
                    row = dict(zip(columns, values))
                    serialized = json.dumps(row, default=encode)
                    size += len(serialized.encode())
                    if len(rows) == 1000 or size > 1024 * 1024:
                        truncated = True
                        break
                    rows.append(json.loads(serialized))
            connection.rollback()
            return {'columns': columns, 'rows': rows, 'truncated': truncated}
    except HTTPException:
        raise
    except psycopg.errors.QueryCanceled:
        raise HTTPException(408, 'Query timed out.')
    except psycopg.Error:
        raise HTTPException(422, 'Query failed. Check columns, types, and connection permissions.')
    finally:
        if 'deadline' in locals():
            deadline.cancel()
        SLOTS.release()
