"""Runnable declaration example. Copy into your project's jobs module."""
from pydantic import BaseModel, ConfigDict, Field
from compute import Job, Resources


class CountInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(max_length=100000)


class CountOutput(BaseModel):
    words: int


def count_words(value, workdir):
    return CountOutput(words=len(value.text.split()))


JOBS = [Job(
    name='example.count_words', version=1,
    handler=count_words, input=CountInput, output=CountOutput,
    resources=Resources(cpu=1, memory_mb=256),
    timeout_seconds=30, max_attempts=2,
)]
