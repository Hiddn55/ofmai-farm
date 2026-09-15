# launchd — the farm survives a reboot on its own

Five agents. After `sudo reboot`, nothing is typed by hand.

| Agent | What | Cadence |
|---|---|---|
| `ai.ofmai.farm.ghost` | the ghost server: REST, dashboard, scheduler, checkpoints, live video | `KeepAlive` |
| `ai.ofmai.farm.planner` | turns today's session plan into ghost jobs | `KeepAlive`, ticks every 60 s |
| `ai.ofmai.farm.bridge` | pulls the OFMAI queue, pushes media, sends events back | `KeepAlive`, ticks every 300 s |
| `ai.ofmai.farm.adb-connect` | reattaches any phone that dropped off, replays its shell login | every 60 s |
| `ai.ofmai.farm.backup` | ledger + phone registry off the machine | 04:30 local |

## Install

```sh
OPERATOR=$(whoami)
mkdir -p ~/Library/LaunchAgents ~/Library/Logs/ofmai-farm
for f in scripts/launchd/ai.ofmai.farm.*.plist; do
  sed "s/OPERATOR/$OPERATOR/g" "$f" > ~/Library/LaunchAgents/"$(basename "$f")"
done
# the bridge does not exist yet (E7.3) — load it once `gitd.farm.cli bridge` does
for f in ghost planner adb-connect backup; do
  launchctl unload ~/Library/LaunchAgents/ai.ofmai.farm.$f.plist 2>/dev/null
  launchctl load  ~/Library/LaunchAgents/ai.ofmai.farm.$f.plist
done
launchctl list | grep ai.ofmai
```

The plists assume the repo is at `~/ofmai-farm` and that `python3` and `adb`
are on the `PATH` written into each file. Adjust both if the machine differs.

## Two things a human must set up first

1. **Automatic login for the operator account** (System Settings → Users &
   Groups). Without an open session the login Keychain stays locked, and
   `security find-generic-password` fails: the bridge has no secret and loops on
   401, the backup cannot reach S3, the alerts go silent. Whether FileVault
   stays on is a decision to make and date.
2. **`~/.ofmai/farm/phones.json`**, `chmod 600`, outside the repo — the map from
   character slug to phone serial. Format in `scripts/farm_adb_connect.sh`.

## After a reboot, in under five minutes

```sh
launchctl list | grep ai.ofmai              # the agents are up
curl -s 127.0.0.1:5055/api/health           # ghost answers
adb devices                                 # every phone in state `device`
PYTHONPATH=. python3 -m gitd.farm.cli devices check   # online, and the right timezone
sh scripts/farm_preflight.sh                # the one-shot verdict
tail -n 5 ~/Library/Logs/ofmai-farm/planner.log
```

Any run left `awaiting_human` by the crash must be resumed or aborted **before**
the planner is allowed to run again:

```sh
curl -s "127.0.0.1:5055/api/skills/runs?limit=5"
curl -X POST 127.0.0.1:5055/api/skills/runs/<id>/resume -H 'Content-Type: application/json' -d '{"action":"abort"}'
```

## Stop everything

```sh
launchctl unload ~/Library/LaunchAgents/ai.ofmai.farm.*.plist
```
