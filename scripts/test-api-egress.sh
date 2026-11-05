#!/usr/bin/env bash
# Synthetic Docker smoke. Never uses the shared Supabase or runtime credentials.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
case $(docker context inspect --format '{{.Endpoints.docker.Host}}') in
  unix://*) ;;
  *) echo 'Use a local Unix-socket Docker context, never a remote daemon.' >&2; exit 1 ;;
esac
compose() {
  if [ -n "${API_EGRESS_COMPOSE:-}" ]; then
    "$API_EGRESS_COMPOSE" "$@"
  elif docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}
export API_ENV_FILE=/dev/null EGRESS_MODE=enforce
export EGRESS_SUPABASE_HOST=synthetic.supabase.co EGRESS_DB_HOST=synthetic.pooler.supabase.com
project="cc-egress-smoke-$$"
files=(-p "$project" -f deploy/api-egress/compose.yaml -f deploy/api-egress/test.compose.yaml)
logs=$(mktemp -d "${TMPDIR:-/tmp}/cc-egress-smoke.XXXXXX")
capture="$project-capture"
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose "${files[@]}" logs --no-color > "$logs/stack.log" 2>&1 || true
    docker logs "$capture" > "$logs/dns.log" 2>&1 || true
    echo "Smoke failed; evidence: $logs" >&2
  fi
  docker rm -f "$capture" >/dev/null 2>&1 || true
  compose "${files[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
compose "${files[@]}" config --quiet
compose "${files[@]}" up -d --build --wait --wait-timeout 120
proxy=$(compose "${files[@]}" ps -q proxy)
netguard=$(compose "${files[@]}" ps -q netguard)
image=$(docker inspect --format '{{.Image}}' "$proxy")
# Docker daemon forwarding happens outside the API namespace. Capture there,
# where forwarded DNS uses port 53; verify a positive control is visible.
docker run -d --name "$capture" --network host --cap-drop ALL --cap-add NET_RAW --cap-add SETUID --cap-add SETGID --cap-add CHOWN \
  --entrypoint tcpdump "$image" -p -U -n -i any -w /tmp/dns.pcap 'port 53' >/dev/null
for attempt in 1 2 3 4 5; do
  if docker logs "$capture" 2>&1 | grep -q 'listening on'; then break; fi
  sleep 1
done
docker logs "$capture" 2>&1 | grep -q "listening on"
docker exec "$proxy" python3 -c '
import socket
packet = bytes.fromhex("abcd01000001000000000000") + b"\x14egress-capture-proof\x07example\x04test\x00\x00\x01\x00\x01"
socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(packet, ("1.1.1.1", 53))'
compose "${files[@]}" exec -T api python /egress-probe.py | tee "$logs/probe.log"
# Verify ingress from the internet-facing network; API may only reply to it.
compose "${files[@]}" exec -T ingress wget -qO- http://127.0.0.1:8000/ready | grep synthetic-egress-api
compose "${files[@]}" logs --no-color proxy > "$logs/proxy.log"
[ "$(grep -c 'must-not-resolve.example.test.*TCP_DENIED' "$logs/proxy.log")" -ge 5 ]
# Firewall counters are independent evidence that both libc and raw DNS sockets
# reached a DROP, rather than merely timing out against an unresponsive resolver.
docker exec "$netguard" iptables -t raw -nvL OUTPUT > "$logs/firewall.log"
awk '$3 == "DROP" && $1 > 0 { found=1 } END { exit !found }' "$logs/firewall.log"
docker stop -t 2 "$capture" >/dev/null
docker logs "$capture" > "$logs/dns.log" 2>&1
docker cp "$capture:/tmp/dns.pcap" "$logs/dns.pcap" >/dev/null
python3 - "$logs/dns.pcap" <<'PYCODE'
from pathlib import Path
import re
import sys
packets = Path(sys.argv[1]).read_bytes()
assert b'egress-capture-proof' in packets, 'DNS capture positive control missing'
assert not re.search(rb'egress-[0-9a-f]{32}|must-not-resolve|secret\x03api\x04resy', packets), 'Rejected DNS name left namespace'
PYCODE
echo 'PASS packet capture: positive control seen, rejected DNS names absent'
# Audit mode still uses the same API network/firewall. Unknown public TLS is
# allowed and logged so operators can find missing destinations before enforcing.
export EGRESS_MODE=audit
compose "${files[@]}" up -d --no-deps proxy
compose "${files[@]}" exec -T api python -c 'import httpx; r=httpx.get("https://example.com", timeout=20); assert r.status_code == 200'
compose "${files[@]}" logs --no-color proxy | grep 'policy=unlisted.*example.com:443.*TCP_TUNNEL'
echo "PASS audit mode allows and logs unlisted host; evidence: $logs"
