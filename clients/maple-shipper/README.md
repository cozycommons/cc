# Maple EXP Shipper

Ships your [Maple Classic EXP Overlay](https://github.com/beanguri/Maple-Classic-Exp-Overlay)
log lines to your Cozy Commons telemetry account, so Muse can read your
training data back (EXP/hr by map, mesos/hr, session history) instead of
you screenshotting the overlay.

The shipper's only tie to the overlay is the `exp_log.json` file format —
a data interface, not a code dependency. It is a single stdlib-only
Python 3 script: nothing to pip install, and overlay updates cannot
break it as long as the log format holds.

## Prerequisites

- macOS with the EXP Overlay installed and its EXP Log turned on. The
  overlay writes `~/Library/Application Support/MapleEXP/exp_log.json`.
- A Cozy Commons telemetry token (below). Python 3 ships with macOS
  (`/usr/bin/python3`); nothing else is needed.

## Get a token

Onboarding mints a personal token (`ccm_...`) for your telemetry
account. It is shown **once** — treat it like a password.

```bash
curl -s -X POST https://api.cozycommons.dev/telemetry/onboard \
  -H 'Content-Type: application/json' \
  -d '{"label": "your-name"}'
# -> {"id": "...", "label": "your-name", "token": "ccm_..."}
```

Anyone can onboard the same way; each token sees only its own data.
Lost the token? There is no recovery — onboard again for a new account,
or ask the backend operator to delete the old one first.

## Install (launchd agent: starts at login, restarts on death)

The shipper lives in the Cozy Commons repo, beside the backend it
ships to, so ingest-contract changes land atomically with the client:

```bash
git clone https://github.com/cozycommons/cc.git
cd cc/clients/maple-shipper
./install.sh
```

`install.sh` copies `shipper.py` to
`~/Library/Application Support/MapleShipper/`, creates `config.json`
there (prompting once for your token), renders the launchd plist into
`~/Library/LaunchAgents/`, and loads it. Logs land in
`~/Library/Logs/MapleShipper/shipper.log`.

Config (`config.json`):

| Key | Meaning |
| --- | --- |
| `token` | Your `ccm_...` telemetry token. Local file only; never sent anywhere but the API. |
| `api_base` | Backend base URL. Default `https://api.cozycommons.dev`. |
| `log_path` | Overlay log path. Default `~/Library/Application Support/MapleEXP/exp_log.json`. |
| `poll_seconds` | How often to check the log for changes. Default 20. |
| `checkpoint_path` | Where shipping progress is kept. Default: `checkpoint.json` beside the config. |

## Test it before you trust it

Dry run — prints exactly what would be sent, touches nothing:

```bash
/usr/bin/python3 shipper.py --dry-run
```

One real pass, in the foreground:

```bash
/usr/bin/python3 shipper.py --once
```

Then confirm the data landed (same token):

```bash
curl -s https://api.cozycommons.dev/telemetry/exp/runs \
  -H 'Authorization: Bearer ccm_YOUR_TOKEN' | head -c 600
```

You should see your log lines with `exp_per_hour`, `mesos_per_hour` and
`net_per_hour` computed. Re-running `--once` sends nothing new: lines
are only re-sent when their totals change.

## How it works

- **First run backfills everything.** The checkpoint starts empty, so
  the first pass ships your *entire* existing `exp_log.json` history —
  every log line the overlay has ever written — not just lines from
  that moment on. Later passes send only new or changed lines.
- Each overlay log line (one day / map / level / class / party size) gets
  a stable `run_id`: a sha256 over its key fields, computed identically
  here and on the backend. Re-posting a line **upserts** it — as a line's
  totals grow during the day, the server row grows with it; nothing
  duplicates.
- `checkpoint.json` records a fingerprint of every line the server has
  confirmed. The checkpoint advances only on confirmed acceptance
  (store-and-forward): quit mid-grind, lose WiFi, close the laptop —
  everything unshipped goes out on the next successful pass.
- The shipper never writes to the overlay's files, never touches the
  game, and sends only the log lines themselves.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.warnerktsang.maple-shipper.plist
rm ~/Library/LaunchAgents/com.warnerktsang.maple-shipper.plist
rm -rf ~/Library/Application\ Support/MapleShipper
```

Your already-shipped telemetry stays in Cozy Commons; delete the whole
account (and its rows) with
`curl -X DELETE https://api.cozycommons.dev/telemetry/account -H 'Authorization: Bearer ccm_YOUR_TOKEN'`.

## Troubleshooting

- **`no token configured`** — `config.json` still has the placeholder or
  an empty token. Paste the `ccm_...` from onboarding.
- **Nothing ships, log file "not readable"** — the overlay hasn't
  written a log yet (play a few minutes with the EXP Log on), or
  `log_path` points somewhere else. Check with `--dry-run`.
- **`ingest failed ... will retry`** — network or backend down. The
  shipper keeps retrying each poll; nothing is lost.
- **A line never appears** — check `~/Library/Logs/MapleShipper/shipper.log`
  for a `server rejected a run` entry; that means the overlay wrote a
  line the backend's validation refused (worth reporting).
