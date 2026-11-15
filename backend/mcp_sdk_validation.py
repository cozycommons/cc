"""Input-redacting MCP SDK adapter, usable without the separate FastMCP package."""
from mcp.server.fastmcp import FastMCP as SdkFastMCP
from mcp.server.fastmcp.exceptions import ToolError as SdkToolError
from pydantic import ValidationError as PydanticValidationError


def describe(errors: list[dict]) -> str:
    return '; '.join(
        'arguments: unexpected fields are not permitted' if error.get('type') == 'extra_forbidden' else
        f"{'.'.join(str(part) for part in error.get('loc', ())) or 'arguments'}: {error.get('msg', 'invalid')}"
        for error in errors
    )


def safe_detail(exc: BaseException) -> str:
    cause = exc if isinstance(exc, PydanticValidationError) else exc.__cause__
    if isinstance(cause, PydanticValidationError):
        return describe(cause.errors(include_url=False))
    return 'arguments do not match the tool schema'


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
