# syntax=docker/dockerfile:1.7
# Sandbox image for untrusted SWF processing. It holds one fixed toolchain
# (JPEXS on a Temurin JRE) and one entrypoint with a fixed set of operations.
# It has no Commons code, credentials or network clients. The host-side
# runner (sandbox.py) adds the runtime limits: no network, read-only root,
# no capabilities, non-root user, memory/CPU/pid caps and a wall-clock kill.
#
#   docker build -t cc-arcade-toolchain:dev backend/arcade/toolchain
FROM python:3.12-slim AS fetch
ARG JPEXS_VERSION=26.5.0
ARG JPEXS_SHA256=8d00c2713a724bb3f7e6c9a64994836ce3a953b5ac264f405d98f92e7c266d33
ADD --checksum=sha256:${JPEXS_SHA256} \
    https://github.com/jindrapetrik/jpexs-decompiler/releases/download/version${JPEXS_VERSION}/ffdec_${JPEXS_VERSION}.zip \
    /fetch/ffdec.zip
# Jansi would otherwise unpack its native library into /tmp, which the runner
# mounts noexec, so ship that library in the read-only image instead.
COPY extract-jansi.py /fetch/extract-jansi.py
RUN python -m zipfile -e /fetch/ffdec.zip /opt/jpexs \
    && rm -f /opt/jpexs/*.exe /opt/jpexs/*.bat \
    && python /fetch/extract-jansi.py /opt/jpexs/lib /opt/jansi

FROM eclipse-temurin:21-jre-noble
COPY --from=fetch /opt/jpexs /opt/jpexs
COPY --from=fetch /opt/jansi /opt/jansi
COPY entrypoint.sh /opt/toolchain/entrypoint.sh
RUN chmod 0555 /opt/toolchain/entrypoint.sh && chmod -R a-w /opt/jpexs /opt/jansi
# JPEXS writes its settings under HOME; the runner mounts /tmp as tmpfs.
ENV HOME=/tmp/home
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["/opt/toolchain/entrypoint.sh"]
