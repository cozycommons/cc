#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Explicit tracked inputs include all Python lock sets, even test-only ones.
args=()
while IFS= read -r path; do
  if [[ "$path" == *.in ]]; then path="${path%.in}.txt"; fi
  args+=(--lockfile "$path")
done < <(git ls-files '*requirements*.in' '*package-lock.json' package-lock.json)
"${OSV_SCANNER:-osv-scanner}" scan source --config osv-scanner.toml "${args[@]}" "$@"
