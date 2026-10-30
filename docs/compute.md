# Shared project jobs

Projects declare typed, versioned Python jobs; the shared PC worker executes them.
The compute API persists small job envelopes in SQLite on a durable volume. Large
inputs and outputs belong in project-owned object storage and are passed as
references. No Supabase or Crowdset dependency is required.

## Declare a job

Copy `backend/compute/example.py` to your project's package, for example
`backend/documents/compute_jobs.py`. Export a `JOBS` list:

```python
from pydantic import BaseModel
from compute import Job, Resources

class Input(BaseModel):
    text: str

class Output(BaseModel):
    words: int

def count(value, workdir):
    return Output(words=len(value.text.split()))

JOBS = [Job(
    name='documents.count', version=1,
    handler=count, input=Input, output=Output,
    resources=Resources(cpu=1, memory_mb=512, gpu=0),
    timeout_seconds=60, max_attempts=2,
)]
```

The function receives validated input and a private, per-attempt working directory.
It returns JSON-compatible output validated against its output model. Increment the
version when changing the contract; retain old declarations until their jobs drain.
Imports should be lightweight: import heavy processing libraries inside the handler.

Set `CC_JOB_MODULES=documents.compute_jobs,another_project.compute_jobs` on the API
and worker. Modules are an allowlist from deployment configuration, never request
parameters. Both deployments must contain the modules and their dependencies.
Adding a handler requires no queue or scheduler code changes. A worker advertises
only its installed job types, so an old worker leaves newer jobs queued.

## Run a local example

From the repository root, create an environment and install
`backend/requirements-compute.txt`. In two terminals with that environment active:

```sh
export PYTHONPATH="$PWD/backend"
export CC_JOB_MODULES=compute.example
export CC_COMPUTE_DB=/tmp/cc-compute-example/jobs.sqlite3
export CC_COMPUTE_PROJECT_TOKENS='{"example":"local-example-producer"}'
export CC_COMPUTE_WORKER_TOKEN=local-example-worker
python -m uvicorn compute.api:configured_app --factory --host 127.0.0.1 --port 8011
```

```sh
export PYTHONPATH="$PWD/backend"
export CC_JOB_MODULES=compute.example
export CC_COMPUTE_URL=http://127.0.0.1:8011
export CC_COMPUTE_WORKER_TOKEN=local-example-worker
python -m compute.worker --root /tmp/cc-compute-example/worker
```

Submit from a project backend and poll the returned ID:

```python
from compute.client import Client

jobs = Client('http://127.0.0.1:8011', 'local-example-producer')
job = jobs.submit('example.count_words@1', {'text': 'hello shared worker'},
                  idempotency_key='example-request-1')
print(jobs.status(job['id']))
```

Production tokens must be generated secrets, distinct for each project and the
worker, and stored in environment configuration. Never expose producer tokens to
the browser: the project API authenticates its users before submitting jobs.
Producer tokens can submit/read only their project's jobs. Worker tokens can
claim and finish jobs but cannot submit. Use HTTPS outside loopback.

## Persistence and execution contract

- SQLite transactions serialize submit/claim/update across API processes. Mount
  the database directory on persistent local storage, back it up, and run one
  control-plane deployment. Do not put it on a network filesystem.
- Project-scoped idempotency keys persist across restarts and terminal states.
  Reusing a key with different input returns 409. Use a new key for a new run.
- Claims carry a fresh attempt token. Heartbeats renew a 120-second lease up to
  the job deadline; expired claims cannot publish. Expired attempts are recovered
  when the API next handles a claim or status request. Retries stop at the declared
  maximum; explicit handler failures also consume attempts.
- Execution is **at least once**. Handlers must make external side effects
  idempotent; a lease fences queue results, not writes to third-party systems.
  Result publication can be replayed with the same claim and result.
- Workers claim only registered versions whose CPU/memory/GPU requirements fit
  their advertised capacity. Configure `CC_WORKER_CPU` (default 4),
  `CC_WORKER_MEMORY_MB` (8192), and `CC_WORKER_GPU` (0; set 1 on a GPU worker).
- v1 has one shared execution slot. Jobs run in FIFO order among eligible jobs.
  The runner alternates between queue sources so continuous Crowdset work does
  not monopolize a PC. Use one runner per PC and the same data root/lock.
- Each generic job runs in a subprocess. The worker kills its process group at
  timeout, on heartbeat failure, or after completion, before releasing its slot.
  It drains the current job on normal shutdown or an updater pause request.
- Resource declarations are admission checks, **not per-job CPU/RAM limits**.
  Use systemd/Docker to cap the worker as a whole. Per-job containers, simultaneous
  GPU allocations, untrusted-code isolation, cancellation, and a live progress
  reporting SDK are outside v1. Handlers are trusted repository code.
- Payload/result/progress metadata is bounded to 256 KiB. Worker logs and attempt
  directories remain under `jobs/<id>/<claim>` for diagnosis. Queue history and
  worker files currently require operator retention/cleanup; do not delete active
  attempts. Generic signed artifact transfers are project-owned for now.

## Crowdset and deployment

Crowdset uses the shared runner through an adapter and declares its resources in
`backend/crowdset/compute_jobs.py`:

| Workload | CPU | RAM | GPU |
| --- | --- | --- | --- |
| Render/process (`h264_nvenc`) | 4 | 8192 MiB | 1 |
| Render/process (`libx264`, explicitly selected) | 4 | 8192 MiB | 0 |
| Ingest or YouTube import | 2 | 2048 MiB | 0 |

The API checks capacity before granting a claim; unsuitable jobs remain queued.
The adapter and generic queue share the same worker capacity configuration.
Crowdset defaults GPU capacity to 1 for NVENC and 0 for libx264; an explicit
`CC_WORKER_GPU` overrides that default. A GPU-disabled worker can ingest while
leaving GPU renders for a capable worker. Rendering is not silently switched to CPU.
Crowdset execution now has a child-process deadline (default four hours) and stops
on heartbeat failure; descendants are killed before the shared slot is released.

Its existing durable queue,
original-object transfer protocol, generation checks and publication logic remain
in place; no migration of pending media jobs is required. Set `CC_COMPUTE_URL`,
`CC_COMPUTE_WORKER_TOKEN`, `CC_JOB_MODULES`, and capacity variables in its worker
environment to let that **same process** alternate Crowdset and other jobs. Do not
start a second compute worker alongside it using a different data root.

The Crowdset installer/updater includes the shared runtime and example declaration.
Custom project modules/dependencies must also be installed on the PC (for example,
from a deployed repository checkout on `PYTHONPATH`). The existing updater manages
its explicit file bundle; it does not automatically deploy arbitrary project code.
An older updater needs two update cycles to expand that bundle: after the first,
the upgraded runner stays healthy without claiming jobs until the shared runtime
arrives. Existing in-flight work drains before either update. The new adapter uses the
resource-aware `claim-v2` operation. Deploy the updated Crowdset API before the
worker; if the API has not upgraded, the worker waits without taking an unchecked
claim. The original claim operation remains available for older workers during
rollout.

`backend/compute/Dockerfile` builds the independent API image; persist `/data`, set
the registry/token environment variables, and route HTTPS to port 8011. It copies
backend source but installs only compute dependencies; add project-specific
packages to your derived image if declarations need them. The same image can run
`python -m compute.worker --root /data/worker` with worker configuration. This change
does not provision Coolify, deploy a service, or modify the PC's live configuration.

## Validation

```sh
PYTHONPATH=backend python -m pytest backend/compute/tests -q
```

Tests cover a second project's declaration, restart persistence, concurrent claims,
project authorization, resource filtering, lease expiry, bounded retries, result
validation/replay, real handler subprocesses, timeout termination, source rotation,
and updater pauses. CI runs this lightweight suite only for compute/infrastructure
changes. Runtime changes also select Crowdset's compatibility tests and image.

## Exclusive interactive GPU sessions

An interactive model-serving session can reserve the PC ahead of queued renders.
The reservation drains any accepted job without cancelling it, then pauses the
whole worker, including CPU-only jobs. It does not change FIFO job order or
interrupt leases, heartbeats, publication, or subprocess cleanup. Rendering
resumes only after the owned model process group has ended and its supervisor
releases the reservation. This implements session priority, not GPU preemption.

The supervisor CLI is **Linux/systemd-specific**. Once a complete CI-approved
release containing `compute.reservation` and `compute.gpu_session` is installed:

```sh
cd ~/.local/share/crowdset-worker
processing-venv/bin/python -m compute.gpu_session --root data -- \
  /path/to/model-server --host 127.0.0.1 --port 8001
```

The command after `--` is trusted operator code. Use a dedicated inference
runtime, not the rendering venv. No model weights or inference packages are
installed by this command. It waits up to four hours for the active job to drain
(`--drain-timeout` changes that bound). A drain timeout never cancels the render.
The Python `serve(root, command, pid_reader, stop)` API takes a PID-reader
callback instead of requiring systemd; it supports portable Unix tests on macOS
and Ubuntu. This does not add Windows support.

`data/gpu-session.json` contains an opaque owner token, owner PID, launch phase
and model PID when known. The supervisor serializes owners with
`gpu-session.lock`, installs its request while holding the updater's existing
`update.lock`, and waits for `gpu-session-ack.json` carrying that token, the
current service PID and a fresh timestamp. An acknowledgment is written only
between jobs, after the accepted job's `run` path returns. A claim already in
flight when the request arrives may be accepted and must drain before this
acknowledgment; GPU loading cannot race it. Both the shared runner and legacy
local-spool runner honor the reservation before claiming more work.

The updater defers all release/recovery work while `gpu-session.json` exists.
It never removes that file. The updater-owned `update-requested` marker has a
separate purpose and must not be used as an RL reservation. Keep both queues
under one worker data root; an unrelated GPU process or worker using another
root is outside this cooperative protocol.

Stop a session normally with Ctrl-C or SIGTERM to its supervisor. Cleanup
terminates and reaps only the process group that supervisor created, checks
that the group has disappeared, then removes only its matching reservation and
acknowledgment. Model startup failure and drain timeout clean up their own
requests. A lost worker acknowledgment stops the model before release.

There is deliberately **no expiry or automatic stale-owner cleanup**. SIGKILL,
power loss, a failed process-group cleanup, or a supervisor crash during launch
can retain ownership. The worker remains paused and the updater defers releases
until an operator recovers it. Inspect without revealing process arguments:

```sh
cat ~/.local/share/crowdset-worker/data/gpu-session.json
cat ~/.local/share/crowdset-worker/data/status.json
nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv
```

A zero-GPU-utilization reading does not prove a model process is gone. Before
removing an orphaned marker, establish that its supervisor and every process
from that serving session have ended. A `launching` phase with no model PID is
ambiguous: the supervisor may have died after creating a child but before
recording its PID. Do not clear that marker based only on age or missing owner
PID; keep the fail-closed pause until process ownership and termination are
verified. Never remove an active owner's marker or `update-requested` as part
of this recovery. There is no force-release command.

### Release transition and validation

The installer and updater bundle include both new modules. An older installed
updater may need two normal CI-approved-main update cycles: its first cycle
installs the new runner/updater but not newly declared modules; incomplete
runtimes remain healthy without claiming jobs. The next cycle installs the
expanded module bundle before stopping/restarting the worker. Existing updater
backups, rollback and source/output preservation still apply. An incomplete
runtime cannot acknowledge a GPU session, so the model cannot start early.
Do not copy an uncommitted patch over the installed worker or bypass release
checks to activate a session.

Focused validation:

```sh
cd backend
source .venv/bin/activate
python -m pytest compute/tests crowdset/tests/test_gpu_worker.py crowdset/tests/test_gpu_updater.py -q
```

Tests cover active-job draining, claims in flight, current-PID/token acknowledgment,
restart persistence, updater independence, owner conflicts, model lifetime and
failure cleanup, SIGKILL before/after process creation, and incomplete release
bundles. They use CPU subprocesses and do not load models or consume GPU memory.
