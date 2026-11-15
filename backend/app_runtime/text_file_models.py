"""Shared manager/MCP schemas; the injected filesystem helper stays stdlib-only."""
from pydantic import BaseModel, ConfigDict, Field


class TextModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class TextReadSpec(TextModel):
    path: str = Field(min_length=1, max_length=2000)
    start_line: int = Field(default=1, ge=1, le=1000000)
    line_count: int = Field(default=200, ge=1, le=2000)


class ExactTextEdit(TextModel):
    old_text: str = Field(min_length=1, max_length=1048576)
    new_text: str = Field(max_length=1048576)


class TextEditSpec(TextModel):
    path: str = Field(min_length=1, max_length=2000)
    expected_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    edits: list[ExactTextEdit] = Field(min_length=1, max_length=32)


class ReadFilesRequest(TextModel):
    files: list[TextReadSpec] = Field(min_length=1, max_length=32)
    max_output_bytes: int = Field(default=65536, ge=1, le=65536)


class EditFilesRequest(TextModel):
    files: list[TextEditSpec] = Field(min_length=1, max_length=16)


class WriteFileRequest(TextModel):
    path: str = Field(min_length=1, max_length=2000)
    content: str = Field(max_length=1048576)
    expected_sha256: str | None = Field(pattern='^[a-f0-9]{64}$')
