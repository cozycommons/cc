# Cozy Arcade toolchain

Arcade lets people decompile, edit and rebuild Flash movies inside Commons.
Ruffle already runs movies safely in the browser. This document covers the
other half: processing an uploaded SWF on the server without that processing
becoming the hazard Flash used to be.

The contract: building is separate from publishing. Decompile and rebuild jobs
run in a disposable, restricted container with one fixed toolchain, bounded
CPU, memory, time and output, no Commons credentials, no host mounts and no
network. The Commons API submits jobs and hands out references to their
results. It never runs a toolchain or an uploader-chosen command in its own
container. A rebuilt movie is an artifact. Publishing it into the catalog is a
separate, explicit step through the catalog's package publisher.

An automatic check passing is compatibility evidence. It is not proof that a
movie is safe, and nothing here treats it as one.

## What exists

`backend/arcade/toolchain/` is a working local prototype:

| File | Role |
| --- | --- |
| `Dockerfile`, `entrypoint.sh` | Sandbox image: Temurin JRE 21 plus JPEXS 26.5.0 (pinned by SHA-256). The entrypoint knows two operations, `export <kinds>` and `import`, and nothing else. |
| `sandbox.py` | Host runner. Starts one container per operation with the limits below, streams input as a tar on stdin, and parses the output tar in memory. |
| `swf.py` | Header gate (signature, declared size) and the synthetic test movie generator. |
| `jobs.py` | `decompile` and `rebuild`, plus the `arcade.swf_decompile@1` and `arcade.swf_rebuild@1` declarations for the shared compute queue (`docs/compute.md`). |

Nothing is mounted in the API: no route, migration or configuration uses it
yet, so merging it changes nothing on cozycommons.dev.

### Operations

- **Decompile** exports the requested JPEXS kinds (`script`, `text`,
  `symbolClass`, `shape`, `morphshape`, `image`, `sound`, `font`,
  `binaryData`). Text parts are normalized to LF.
- **Rebuild** takes edited classes (`scripts/<package>/<Class>.as`). It
  re-exports the movie's scripts, keeps only the submitted classes whose text
  differs, compiles just those into a copy of the movie with
  `-importScript`, then re-exports the result and checks it. Every compiled
  class must have changed, and every other class must decompile exactly as
  before. Otherwise the job fails.

The changed-classes rule comes from real games. A full recompile of an
unchanged Battle movie produced a "Scope depth is unbalanced" VerifyError,
because the decompiler does not round-trip every method. Classes nobody edited
keep their original bytecode.

Two JPEXS behaviors shaped the checks:

- `-importScript` exits 0 and prints nothing both when it compiles a class and
  when it silently skips one. The first fixture put two classes in one ABC
  script, and JPEXS skipped both. A class the movie does not contain is also
  skipped. Rebuild therefore refuses classes that are not in the movie and
  verifies its output by re-exporting it.
- JPEXS prints progress lines that name classes, and a class named
  `AppError` would look like an error. Only `SEVERE`, `Exception` and
  "error" lines that are not progress lines count. A compile error exits 1
  with a `SEVERE ... line N` message, which the job reports.

Binary parts (images, sounds, fonts) come out byte-different on every export,
so only text parts can be compared. Importing non-script parts and adding new
classes are not supported yet.

## Threat model

The input is an arbitrary SWF from a user, plus, for a rebuild, arbitrary
ActionScript source. Assume both are hostile.

| Threat | Mitigation | Remaining risk |
| --- | --- | --- |
| A parser bug in JPEXS or the JVM gives the movie code execution | The code runs in a container with `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, user 65534, no host mounts, no environment secrets, `/tmp` as a `noexec,nosuid,nodev` tmpfs, and `--pull never` on a fixed image. It sees only its own input. | A kernel or container-runtime escape. Set `CC_ARCADE_TOOLCHAIN_RUNTIME=runsc` (gVisor) on the production worker, and run that worker on a host without Commons secrets. |
| Compression bombs (CWS zlib, ZWS LZMA) | The header gate refuses movies over 64 MiB compressed or declaring more than 256 MiB uncompressed, reading only 8 bytes. JPEXS stops inflating at the declared length: a 4.7 MB movie that inflates to 1 GiB but declares 1 KB came back as an empty export in 2.3 s. | A movie that honestly declares 256 MiB inflates inside the container, which the memory cap bounds. |
| Resource exhaustion | 2 CPUs, 1536 MiB memory with no swap (JVM heap at 70% of it), 256 pids, 1024 open files, no core dumps, a 512 MiB tmpfs that also bounds the output, and a 300 s wall clock after which the container is force-removed by name. `--log-driver none` keeps the daemon from storing output; the host keeps the last 64 KiB of the log. The compute queue runs one job at a time. | A run can use its full budget. Repeated submissions are throttled by whoever submits (admin-only at first). |
| Path traversal and links in exports | JPEXS writes only into the container's tmpfs. The host never extracts the output to disk. It reads the tar in memory and rejects absolute paths, `..`, backslashes, symlinks, hard links, devices and FIFOs, with caps of 20,000 files and 256 MiB. | None known. |
| Command or argument injection | The host passes an argv list, never a shell. Operations are a fixed set, export kinds are allowlisted in the job model and again in the entrypoint, and source paths must be `scripts/.../*.as` with no `..`. The job models refuse unknown fields. | None known. |
| Hostile source in a rebuild | JPEXS's own AS3 compiler compiles it inside the same sandbox. Source size is capped at 192 KiB per job (the queue's payload limit is 256 KiB). | Compiler bugs are contained like parser bugs. |
| The output movie is malicious | Rebuild output is treated as untrusted as the input. It plays only in the locked-down Ruffle player on its own origin (arcade-1nv.3). Publication goes through the package publisher (arcade-1nv.1) and its validation, by an explicit action. | Ruffle is the runtime boundary for playback, as for any upload. |
| Credential exposure | Jobs carry short-lived signed URLs, one to read the movie and one to write the result. The worker holds no Storage or database credential, and the sandbox holds nothing. Only HTTPS URLs are accepted (plain HTTP only on loopback, for tests). | A signed URL in the queue database is usable until it expires. Keep expiries short. |
| Docker access on the worker | Starting containers needs the Docker socket, which is root-equivalent on that host. | Use rootless Docker or a dedicated VM for the worker. Never give the Commons API container the socket. |
| Toolchain supply chain | JPEXS is downloaded once at image build and checked against a pinned SHA-256. The JRE base tag follows Temurin 21 security updates. | Pin the base image by digest when a production image is built. |
| Leaking game content | Uploads, decompiled source and rebuilt movies live only in private Storage. Tests use hand-assembled synthetic movies; no game file, decompiled source or package content is in this public repository. | Operator discipline. |

## Placement

Decision: no separate frontend or API. Routes stay in the shared FastAPI app
under `/arcade`. Jobs go on the existing shared compute queue
(`docs/compute.md`). Execution happens on a compute worker that has Docker,
and every operation runs in its own sandbox container from the toolchain
image.

Reasons, from the policy in `docs/deployment.md#project-placement-policy`:

- Toolchain runs are slow, CPU-heavy background work: a separate worker.
- The toolchain is a substantial, incompatible dependency (a JRE and JPEXS;
  the image is about 530 MB) that the API image should not carry.
- It processes hostile input and needs the Docker socket, so it must not run
  inside the Commons API container or on a host that holds its secrets.

Tradeoffs: the worker host needs Docker (ideally rootless, with gVisor), the
toolchain image needs building and updating there, and toolchain work shares
the queue's single execution slot with other compute jobs. The compute
control plane and a Docker-capable worker are prerequisites, and neither is
deployed by this change.

## AS3 from source

Decision: v1 uses JPEXS only, compiling edited classes into an existing movie.
That covers modding uploaded games. Building a whole project from source
(a new game, or a full rebuild of a movie) is deferred. When it is needed, add
the Apache Flex SDK's `mxmlc` as a second fixed toolchain image behind the same
sandbox, because it is the one option that builds existing AS3 projects as
written.

| Option | License | Fit |
| --- | --- | --- |
| JPEXS 26.5.0 (in use) | Application GPL-3.0, `ffdec_lib` LGPL-3.0 (both license files ship in the release zip) | Decompiles and compiles changed classes into an existing movie. Not a project build tool. |
| Apache Flex SDK (`mxmlc`) | Apache-2.0 | Builds AS3/MXML projects as written. Needs Adobe's `playerglobal.swc`, which is distributed under Adobe's terms rather than Apache-2.0. Last release 4.16.1 (2017). |
| Apache Royale | Apache-2.0 | Successor to Flex, mainly targeting JavaScript. Its SWF output also needs `playerglobal.swc`. |
| Haxe | Compiler GPL-2.0-or-later, standard library MIT | Emits SWF directly without Adobe libraries, but its language is Haxe, not AS3. Suits new games, not editing existing ones. |

The Flex release date, Royale's SWF status and Haxe's current Flash-target
support are from prior knowledge and were not re-verified for this document.

### JPEXS license and running it as a service

The JPEXS command line is part of the GPL-3.0 application (`ffdec-cli.jar`
launches `ffdec.jar`). The parsing library `ffdec_lib` is LGPL-3.0. Commons
runs the unmodified release as a separate process and exchanges only files
with it, so Commons' own code is not a derivative work and takes on no GPL
obligation. GPL-3.0 is not the AGPL, so letting users submit jobs over the
network is not "conveying" and needs no source offer. The movies JPEXS
produces are the user's data and are not covered by its license.

Obligations would start if we distributed JPEXS, for example by publishing
the toolchain image to a public registry: ship its license and point to the
corresponding upstream source. Modifying JPEXS would make those modifications
GPL-3.0 when distributed. Linking `ffdec_lib` into our own Java code would
bring in the LGPL terms. Neither is planned.

The JPEXS release also bundles `playerglobal32_0.swc` and `airglobal.swc`,
which its AS3 compiler uses. They are Adobe's API stubs, and their
redistribution terms are not covered by JPEXS's license. That is one more
reason to keep the toolchain image private.

## Job API

The compute jobs exist now. The Commons routes and bucket are the proposed
next step and are not built.

Compute jobs (`jobs.py`):

| Job | Input | Output |
| --- | --- | --- |
| `arcade.swf_decompile@1` | `movie_url`, `result_url`, `kinds` (default `["script"]`) | `movie_sha256`, `result_sha256`, `files`, `bytes`; the parts are uploaded to `result_url` as a `.tar.gz` |
| `arcade.swf_rebuild@1` | `movie_url`, `result_url`, `scripts` (path to edited source) | `movie_sha256`, `result_sha256`, `compiled`, `unchanged`; the movie is uploaded to `result_url` |

Both have one attempt and declare 2 CPUs and 2 GiB. Their deadlines (420 s and
1020 s) sit above the sandbox's 300 s per run, so the sandbox's own timeout,
which removes the container, fires before compute kills the handler.

Proposed Commons routes, verified admins only until uploads with owners
(arcade-1nv.10) exist, and off unless the compute URL and producer token are
configured:

- `POST /arcade/toolchain/jobs` with `{"operation": "decompile" | "rebuild", "movie": <upload id>, "kinds" | "scripts"}`.
  The API checks the caller and the header gate, creates a signed download URL
  for the upload and a signed upload URL for the result, submits the compute
  job with an idempotency key, and returns `202 {"id", "status"}`.
- `GET /arcade/toolchain/jobs/{id}` returns the status and, when finished,
  the summary and a short-lived signed download URL for the artifact.
- A private `arcade-toolchain` bucket holds `uploads/<owner>/<sha256>.swf` and
  `results/<job id>/{parts.tar.gz,movie.swf}`. Browser roles get no direct
  access, as with `arcade-packages`.

Publishing a rebuilt movie into the catalog, and test-playing it in the
sandboxed player, are separate actions owned by arcade-1nv.1 and
arcade-1nv.3.

## Running it locally

```sh
docker build -t cc-arcade-toolchain:dev backend/arcade/toolchain
cd backend && python -m pytest tests/test_arcade_toolchain.py -v
```

The suite covers the header gate, output parsing (traversal, links, devices,
count and size caps), the container flags, changed-class selection and the
silent-skip check with a stand-in toolchain, and the job models' URL, path and
size limits. When the image is present it also runs the real toolchain: it
decompiles a hand-assembled two-class movie, edits one class, rebuilds, and
checks that the edited class changed and the other did not. It also checks
that a syntax error fails the job, and runs both jobs end to end through a
loopback stand-in for signed Storage URLs. Without the image, those three
tests are skipped. `CC_ARCADE_TOOLCHAIN_IMAGE` selects another image tag.

Not verified: the rebuilt synthetic movie has not been played in Ruffle (its
classes are plain objects with no document class); signed upload URLs have
not been exercised against live Supabase Storage; and gVisor and rootless
Docker have not been tried with this image.
