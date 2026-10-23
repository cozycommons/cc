from pydantic import BaseModel, ConfigDict
from compute import Job, Resources


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str


class Output(BaseModel):
    text: str


def uppercase(value, directory):
    return {'text': value.text.upper()}


def fail(value, directory):
    raise RuntimeError('intentional test failure')


def hang(value, directory):
    import os
    import time
    (directory / 'handler.pid').write_text(str(os.getpid()))
    time.sleep(60)


JOBS = [
    Job('alpha.uppercase', 1, uppercase, Input, Output, max_attempts=2),
    Job('beta.uppercase', 1, uppercase, Input, Output),
    Job('alpha.gpu', 1, uppercase, Input, Output, resources=Resources(gpu=1)),
    Job('alpha.fail', 1, fail, Input, Output),
    Job('alpha.hang', 1, hang, Input, Output, timeout_seconds=1),
]
