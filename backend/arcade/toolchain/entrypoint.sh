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
# This shell is PID 1, which ignores signals sent from inside the container,
# so it runs the operation as a child, kills that child at the deadline and
# exits. When PID 1 exits the kernel kills everything left (JPEXS included).
if [ -z "${TOOLCHAIN_TIMED:-}" ]; then
  deadline="${TOOLCHAIN_DEADLINE:-300}"
  case "$deadline" in
    ''|0*|*[!0-9]*) echo "invalid deadline" >&2; exit 64 ;;
  esac
  # A background job's stdin is /dev/null, so hand it the real one on fd 3.
  exec 3<&0
  TOOLCHAIN_TIMED=1 "$0" "$@" 0<&3 3<&- &
  operation=$!
  exec 3<&-
  ( sleep "$deadline"; kill -KILL "$operation" 2>/dev/null ) &
  status=0
  wait "$operation" || status=$?
  [ "$status" -eq 137 ] && echo "toolchain deadline or memory limit reached" >&2
  exit "$status"
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
