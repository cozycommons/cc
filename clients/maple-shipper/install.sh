#!/bin/bash
# Install the Maple EXP shipper as a launchd agent (starts at login,
# restarts on death). Safe to re-run: it refreshes the script and the
# agent, and never overwrites an existing config.json.
set -eu

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/Library/Application Support/MapleShipper"
LOG_DIR="$HOME/Library/Logs/MapleShipper"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.warnerktsang.maple-shipper.plist"
PLIST_PATH="$AGENTS_DIR/$PLIST_NAME"

mkdir -p "$INSTALL_DIR" "$LOG_DIR" "$AGENTS_DIR"
cp "$SOURCE_DIR/shipper.py" "$INSTALL_DIR/shipper.py"

if [ ! -f "$INSTALL_DIR/config.json" ]; then
  cp "$SOURCE_DIR/config.example.json" "$INSTALL_DIR/config.json"
  echo "Created $INSTALL_DIR/config.json"
  printf "Paste your Cozy Commons telemetry token (ccm_...): "
  read -r TOKEN || TOKEN=""
  if [ -n "$TOKEN" ]; then
    # Replace the placeholder without echoing the token anywhere.
    TOKEN="$TOKEN" /usr/bin/python3 - "$INSTALL_DIR/config.json" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    config = json.load(f)
config["token"] = os.environ["TOKEN"]
with open(path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
PYEOF
    echo "Token saved to config.json (it is never printed or logged)."
  else
    echo "No token entered — edit $INSTALL_DIR/config.json before the agent can ship."
  fi
else
  echo "Keeping existing $INSTALL_DIR/config.json"
fi

sed -e "s|__HOME__|$HOME|g" -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
  "$SOURCE_DIR/$PLIST_NAME" > "$PLIST_PATH"

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "Installed and loaded $PLIST_NAME"
echo "Logs: $LOG_DIR/shipper.log"
echo "Test by hand: /usr/bin/python3 \"$INSTALL_DIR/shipper.py\" --once"
