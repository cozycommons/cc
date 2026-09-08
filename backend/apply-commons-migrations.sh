#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMONS_ONLY=1 exec bash "$script_dir/apply-shared-migrations.sh"
