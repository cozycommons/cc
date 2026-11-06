#!/bin/sh
set -eu
mkdir -p /workspace/home /workspace/services /workspace/logs
if [ ! -f /workspace/AGENTS.md ]; then
    cp /opt/app-AGENTS.md /workspace/AGENTS.md
fi
exec supervisord -n -c /etc/supervisor/supervisord.conf
