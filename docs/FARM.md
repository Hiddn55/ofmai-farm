# OFMAI farm — warming, publishing, replies

This fork adds a *farm* layer on top of ghost: accounts bound to devices, a
day-by-day warming policy with hard caps, humanised input, two skills
(`ofmai_instagram`, `ofmai_tiktok`) and a planner that turns the policy into
ghost jobs. Nothing in ghost's core is modified; upstream merges stay clean.

The operating rules (why Android, one account = one device = one IP, US
proxies, what a day of warming looks like) live in the OFMAI repo under
`docs/social/`. This file is the code map.

## Map

| Path | What |
|---|---|
| `gitd/farm/human.py` | `SessionProfile` (one motor signature per session) + `HumanInput`: tap with tremor and hold, feed swipes with drift and variable speed, per-character typing with typos, log-normal pauses and watch times |
| `gitd/farm/policy.py` | phases (consume → light → network → cruise, +3 days each on TikTok), `DailyBudget` (40–100 % of the caps, seeded per account and day, one rest day a week), `BudgetTracker` (caps + like/view ≤ 15 %, follow/visit ≤ 30 %), `plan_sessions` (2–4 sessions, drifting windows, never 01–07), health state machine |
| `gitd/farm/health.py` | on-screen signals: action block, verification, logged out, suspended; zero-reach heuristic |
| `gitd/farm/models.py` · `ledger.py` | `farm_accounts`, `farm_actions`, `farm_signals`; `open_session()` refuses unhealthy accounts; records every counted action |
| `gitd/farm/warm.py` | the session loop, platform-agnostic, driven through a `PlatformAdapter` |
| `gitd/farm/skillkit.py` | `WarmSessionAction`: glue between a ghost workflow and the loop; `FARM_FAST=1` runs on a virtual clock |
| `gitd/farm/planner.py` | every minute, enqueue due sessions as `skill_workflow` jobs (idempotent via `farm_planned`) |
| `gitd/farm/cli.py` | `python -m gitd.farm.cli …` |
| `gitd/skills/ofmai_instagram/` · `ofmai_tiktok/` | `elements.yaml`, popups, adapters, `warm_session` and `post_video` workflows |
| `tests/test_farm_*.py` | 39 unit tests, no device needed: `sh scripts/farm_tests.sh` |

## Daily use

```sh
# register an account: day 1 = today unless --created-on is given
python -m gitd.farm.cli accounts add instagram @eva.moore --device R58N1234 --tz America/New_York --niche "fitness,ootd,gymgirl"
python -m gitd.farm.cli accounts list
python -m gitd.farm.cli budget instagram @eva.moore      # today's caps and what was spent
python -m gitd.farm.cli plan instagram @eva.moore        # today's session times
python -m gitd.farm.cli run instagram @eva.moore --minutes 3   # one session now (through ghost's runner)
python -m gitd.farm.cli daemon                           # the planner, next to `python3 run.py`
```

Sessions also appear in ghost's Scheduler tab (trigger `farm`) with logs and
a `Data: {...}` summary (videos, likes, follows, comments, detours, health).

## What the session does

Opens the app with human pacing, goes to Reels / For You, then until the
minutes are up: watch (log-normal, with quick skips and lingers), maybe like
(double-tap 60 % of the time), maybe save, maybe open the author's profile
and follow, maybe comment from the supplied pool, take a detour every 12–30
videos (niche hashtag search, Instagram stories), sometimes put the phone
down for 20–90 s. Every counted action asks the ledger first. Any health
signal on screen ends the session and moves the account to cooldown /
verification / suspended; the planner then stops scheduling it until a human
clears it (`accounts clear-health`).

## Selectors are not verified yet

`elements.yaml` in both skills comes from en-US accessibility labels and
ghost's public TikTok ids. First thing on the Mac mini: run Skill Miner on
each app, fix the ids, run `warm_session` with `--minutes 2` while watching
the live stream, then fill `tested_on` in `skill.yaml`. Content-desc first,
resource-id second, coordinates never.

## Bench dry run without a phone

```sh
FARM_FAST=1 PYTHONPATH=. python -m pytest tests/test_farm_skills.py -q
```

## Not done yet (next)

- comment / DM reply workflows (`comment_reply`, `dm_reply` actions are
  already budgeted in the policy)
- OFMAI bridge: content queue (S3 keys + captions per character), comment
  pool per persona, events back to OFMAI
- AIGC toggle position on TikTok's post screen (best effort today)
- Portal companion app for faster UI reads on the farm phones
