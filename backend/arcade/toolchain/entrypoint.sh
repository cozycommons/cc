#!/bin/sh
# Fixed operations only. Input is a tar on stdin that the trusted host runner
# built; output is a tar of /tmp/job/out on stdout. Logs go to stderr.
#   export <kinds>   in/movie.swf -> out/<kind folders>
#   import           in/movie.swf + in/scripts/ -> out/movie.swf
# The kind allowlist lives in the host's job model; this script only refuses
# characters a kind list cannot contain.
set -eu

# The whole operation dies at TOOLCHAIN_DEADLINE seconds even if the worker
# that started it is gone; the daemon then removes the container (--rm).
if [ -z "${TOOLCHAIN_TIMED:-}" ]; then
  case "${TOOLCHAIN_DEADLINE:-300}" in
    ''|*[!0-9]*) echo "invalid deadline" >&2; exit 64 ;;
  esac
  TOOLCHAIN_TIMED=1 exec timeout -s KILL "${TOOLCHAIN_DEADLINE:-300}" "$0" "$@"
fi

op="${1:-}"
mkdir -p /tmp/home /tmp/job/in /tmp/job/out
cd /tmp/job
# Heap is a share of the container's memory limit.
ffdec() {
  java -Djava.awt.headless=true -XX:+UseSerialGC -XX:MaxRAMPercentage=70 \
    -Dlibrary.jansi.path=/opt/jansi -Djansi.mode=strip \
    -jar /opt/jpexs/ffdec-cli.jar "$@"
}
case "$op" in
  export)
    case "${2:-}" in
      ''|*[!a-zA-Z,]*) echo "invalid export kinds" >&2; exit 64 ;;
    esac
    tar -x -m -o -C in
    ffdec -export "$2" out in/movie.swf >&2
    ;;
  import)
    tar -x -m -o -C in
    ffdec -importScript in/movie.swf out/movie.swf in/scripts >&2
    ;;
  *)
    echo "unknown operation" >&2; exit 64 ;;
esac
tar -c -C out .
