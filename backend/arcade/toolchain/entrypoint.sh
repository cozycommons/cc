#!/bin/sh
# Fixed operations only. Input is a tar on stdin that the trusted host runner
# built; output is a tar of /tmp/job/out on stdout. Logs go to stderr.
#   export <kinds>   in/movie.swf -> out/<kind folders>
#   import           in/movie.swf + in/scripts/ -> out/movie.swf
#   help             JPEXS usage (for diagnosis)
set -eu
op="${1:-}"
mkdir -p /tmp/home /tmp/job/in /tmp/job/out
cd /tmp/job
# The heap is a share of the container's memory limit.
ffdec() {
  java -Djava.awt.headless=true -XX:+UseSerialGC -XX:MaxRAMPercentage=70 \
    -Dlibrary.jansi.path=/opt/jansi -Djansi.mode=strip \
    -jar /opt/jpexs/ffdec-cli.jar "$@"
}
unpack() {
  tar -x -m -C in --no-same-owner --no-same-permissions
}
case "$op" in
  export)
    case "${2:-}" in
      ''|*[!a-zA-Z,]*) echo "invalid export kinds" >&2; exit 64 ;;
    esac
    unpack
    ffdec -export "$2" out in/movie.swf >&2
    ;;
  import)
    unpack
    ffdec -importScript in/movie.swf out/movie.swf in/scripts >&2
    ;;
  help)
    ffdec --help >&2 || true
    exit 0
    ;;
  *)
    echo "unknown operation" >&2; exit 64 ;;
esac
tar -c -C out .
