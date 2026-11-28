# syntax=docker/dockerfile:1.7
# Sandbox image for untrusted SWF processing. It holds one fixed toolchain
# (JPEXS on a minimal Java 21 runtime) and one entrypoint with a fixed set of
# operations. It has no Commons code, credentials, package manager cache or
# network clients. The host-side runner (sandbox.py) adds the runtime limits:
# no network, read-only root, no capabilities, non-root user, memory/CPU/pid
# caps and a wall-clock kill.
#
#   docker build -t cc-arcade-toolchain:dev backend/arcade/toolchain
FROM eclipse-temurin:21-jdk-alpine AS build
ARG JPEXS_VERSION=26.5.0
ARG JPEXS_SHA256=8d00c2713a724bb3f7e6c9a64994836ce3a953b5ac264f405d98f92e7c266d33
ADD --checksum=sha256:${JPEXS_SHA256} \
    https://github.com/jindrapetrik/jpexs-decompiler/releases/download/version${JPEXS_VERSION}/ffdec_${JPEXS_VERSION}.zip \
    /fetch/ffdec.zip
# JPEXS without its desktop launchers, icons and GUI-only libraries (look and
# feel, editor, video, tree table). The CLI starts through the GUI's main
# class, which loads the debugger and JNA libraries, so those stay. License
# files stay.
# Jansi's native library is unpacked here: at run time it would be written to
# /tmp, which is mounted noexec.
RUN unzip -q /fetch/ffdec.zip -d /opt/jpexs \
    && cd /opt/jpexs \
    && rm -f *.exe *.bat *.icns *.ico *.png ffdec ffdec.sh CHANGELOG.md *.metainfo.xml \
    && rm -f lib/substance*.jar lib/flamingo*.jar lib/trident*.jar lib/jsyntaxpane*.jar \
       lib/vlcj*.jar lib/treetable.jar \
    && arch="$(uname -m | sed 's/aarch64/arm64/')" \
    && mkdir /opt/jansi \
    && unzip -q -j lib/jansi-*.jar "org/fusesource/jansi/internal/native/Linux/$arch/libjansi.so" -d /opt/jansi
# Only the modules JPEXS uses (jdeps over ffdec.jar and ffdec_lib.jar).
RUN jlink --add-modules java.base,java.compiler,java.desktop,java.logging,java.scripting,jdk.unsupported \
      --strip-debug --no-man-pages --no-header-files --compress=zip-6 --output /opt/jre

FROM alpine:3
# gcompat lets Jansi's glibc-built library load on musl.
RUN apk add --no-cache gcompat
COPY --from=build /opt/jre /opt/jre
COPY --from=build /opt/jpexs /opt/jpexs
COPY --from=build /opt/jansi /opt/jansi
COPY --chmod=0555 entrypoint.sh /opt/toolchain/entrypoint.sh
# JPEXS writes its settings under HOME; the runner mounts /tmp as tmpfs.
ENV PATH=/opt/jre/bin:$PATH HOME=/tmp/home
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["/opt/toolchain/entrypoint.sh"]
