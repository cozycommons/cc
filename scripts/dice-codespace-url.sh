#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: scripts/dice-codespace-url.sh <codespace-name>\n'
}

codespace_name="${1:-}"
if [[ ! "$codespace_name" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
  usage >&2
  exit 2
fi

for required_command in gh curl; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$required_command" >&2
    exit 1
  fi
done

max_attempts="${DICE_CODESPACE_MAX_ATTEMPTS:-48}"
poll_seconds="${DICE_CODESPACE_POLL_SECONDS:-5}"
case "$max_attempts:$poll_seconds" in
  *[!0-9:]*|0:*|*:0)
    printf 'Codespace wait settings must be positive integers.\n' >&2
    exit 2
    ;;
esac

state="$(gh codespace view -c "$codespace_name" --json state -q .state)"
if [[ "$state" == "Shutdown" ]]; then
  printf 'Starting Codespace %s...\n' "$codespace_name"
  gh api --method POST "/user/codespaces/$codespace_name/start" --silent
fi

attempt=0
while ((attempt < max_attempts)); do
  state="$(gh codespace view -c "$codespace_name" --json state -q .state)"
  if [[ "$state" == "Available" ]] &&
    gh codespace ssh -c "$codespace_name" -- \
      'curl -fsS http://127.0.0.1:8000/health >/dev/null && curl -fsS http://127.0.0.1:8080/dice >/dev/null' \
      >/dev/null 2>&1; then
    break
  fi
  attempt=$((attempt + 1))
  sleep "$poll_seconds"
done

if [[ "$state" != "Available" || "$attempt" -ge "$max_attempts" ]]; then
  printf 'Codespace sandbox did not become ready. Inspect /tmp/dice-codespace.log.\n' >&2
  exit 1
fi

browse_url="$(gh codespace ports -c "$codespace_name" \
  --json sourcePort,browseUrl,visibility \
  -q '.[] | select(.sourcePort == 8080 and .visibility == "private") | .browseUrl')"
if [[ ! "$browse_url" =~ ^https://[a-z0-9-]+-8080\.app\.github\.dev$ ]]; then
  printf 'Could not find the private Dice port 8080 URL.\n' >&2
  exit 1
fi

preview_url="$browse_url/dice"
sign_in_url="$(curl -sS -o /dev/null -D - "$preview_url" |
  tr -d '\r' | sed -n 's/^[Ll]ocation: //p' | head -n 1)"
if [[ ! "$sign_in_url" == https://github.dev/pf-signin\?* ]]; then
  printf 'GitHub did not return the expected private-port sign-in URL.\n' >&2
  exit 1
fi

printf 'Dice sandbox: %s\n' "$preview_url"
printf 'Mobile GitHub sign-in: %s\n' "$sign_in_url"
