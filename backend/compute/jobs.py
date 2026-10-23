"""Trusted declarations loaded by both the control plane and worker."""
from dataclasses import dataclass, field
from importlib import import_module
import re
import os
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field


class Resources(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    cpu: int = Field(default=1, ge=1, le=256)
    memory_mb: int = Field(default=512, ge=1)
    gpu: int = Field(default=0, ge=0, le=1)

    @classmethod
    def environment(cls, default_gpu=0):
        return cls(cpu=int(os.environ.get('CC_WORKER_CPU', '4')),
                   memory_mb=int(os.environ.get('CC_WORKER_MEMORY_MB', '8192')),
                   gpu=int(os.environ.get('CC_WORKER_GPU', str(default_gpu))))

    def fits(self, capacity):
        return all(getattr(self, key) <= getattr(capacity, key) for key in ('cpu', 'memory_mb', 'gpu'))


@dataclass(frozen=True)
class Job:
    name: str
    version: int
    handler: Callable
    input: type[BaseModel]
    output: type[BaseModel]
    resources: Resources = field(default_factory=Resources)
    timeout_seconds: int = 300
    max_attempts: int = 1

    def __post_init__(self):
        if not re.fullmatch(r'[a-z][a-z0-9_-]*\.[a-z][a-z0-9_.-]*', self.name):
            raise ValueError('Job names must be project.name')
        if not 1 <= self.version or not 1 <= self.timeout_seconds <= 86400 or not 1 <= self.max_attempts <= 10:
            raise ValueError('Invalid job version, timeout or retry limit')
        if not callable(self.handler) or not issubclass(self.input, BaseModel) or not issubclass(self.output, BaseModel):
            raise ValueError('Jobs require a callable and Pydantic input/output models')

    @property
    def key(self):
        return f'{self.name}@{self.version}'

    @property
    def project(self):
        return self.name.split('.')[0]


class Registry:
    def __init__(self, jobs=()):
        self.jobs = {}
        for job in jobs:
            if job.key in self.jobs:
                raise ValueError(f'Duplicate job declaration: {job.key}')
            self.jobs[job.key] = job

    @classmethod
    def load(cls, modules):
        # Module names come only from deployment configuration, never a request.
        return cls(job for module in modules for job in import_module(module).JOBS)

    def get(self, key):
        try:
            return self.jobs[key]
        except KeyError:
            raise ValueError(f'Unknown job type: {key}') from None
