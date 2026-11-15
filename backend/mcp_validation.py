"""MCP tool-argument errors that never echo what the agent sent.

Pydantic validation errors carry each failing value under `input` (for a missing
argument, every argument that was sent). Legacy /<project>/mcp tools take the
caller's api_token as an argument, so a call missing any other argument would
put the token in FastMCP 3's warning log and in the error text returned to the
agent. Logs and errors keep only each failure's location and message.
"""
import logging

from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import Middleware
from pydantic import ValidationError as PydanticValidationError
from mcp_sdk_validation import FastMCP, describe, safe_detail

# FastMCP 3 logs "Invalid arguments for tool %r: %s" with `errors()` from this logger.
FASTMCP_SERVER_LOGGER = 'fastmcp.server.server'
INVALID_ARGUMENTS = 'Invalid arguments for tool'




class RedactToolArgumentLogs(logging.Filter):
    """Rewrite FastMCP 3's invalid-argument warning to loc and msg only."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and record.msg.startswith(INVALID_ARGUMENTS):
            args = record.args if isinstance(record.args, tuple) else ()
            detail = args[1] if len(args) > 1 else None
            if isinstance(detail, list) and all(isinstance(error, dict) for error in detail):
                safe = describe(detail)
            else:
                # The str(e) fallback is pydantic's own text, input_value included.
                safe = 'arguments do not match the tool schema'
            record.msg = INVALID_ARGUMENTS + ' %r: %s'
            record.args = (args[0] if args else '?', safe)
        return True


def install_log_filter() -> None:
    logger = logging.getLogger(FASTMCP_SERVER_LOGGER)
    if not any(isinstance(f, RedactToolArgumentLogs) for f in logger.filters):
        logger.addFilter(RedactToolArgumentLogs())


class ToolArgumentErrors(Middleware):
    """FastMCP 3: return argument-validation failures without input values."""

    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except (ValidationError, PydanticValidationError) as e:
            raise ToolError(f'{INVALID_ARGUMENTS} {context.message.name!r}: {safe_detail(e)}') from None
