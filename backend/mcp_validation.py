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
from mcp.server.fastmcp import FastMCP as SdkFastMCP
from mcp.server.fastmcp.exceptions import ToolError as SdkToolError
from pydantic import ValidationError as PydanticValidationError

# FastMCP 3 logs "Invalid arguments for tool %r: %s" with `errors()` from this logger.
FASTMCP_SERVER_LOGGER = 'fastmcp.server.server'
INVALID_ARGUMENTS = 'Invalid arguments for tool'


def describe(errors: list[dict]) -> str:
    return '; '.join(
        f"{'.'.join(str(part) for part in error.get('loc', ())) or 'arguments'}: {error.get('msg', 'invalid')}"
        for error in errors
    )


def safe_detail(exc: BaseException) -> str:
    cause = exc if isinstance(exc, PydanticValidationError) else exc.__cause__
    if isinstance(cause, PydanticValidationError):
        return describe(cause.errors(include_url=False))
    return 'arguments do not match the tool schema'


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


class FastMCP(SdkFastMCP):
    """The MCP SDK's FastMCP for legacy servers, without input values in tool errors.

    The SDK validates arguments inside Tool.run and wraps pydantic's error, with
    every `input_value`, in the ToolError text returned to the agent.
    """

    async def call_tool(self, name, arguments):
        try:
            return await super().call_tool(name, arguments)
        except SdkToolError as e:
            if isinstance(e.__cause__, PydanticValidationError):
                raise SdkToolError(f'Error executing tool {name}: {safe_detail(e)}') from None
            raise
