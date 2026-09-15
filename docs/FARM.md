# OFMAI farm — warming, publishing, replies

This fork adds a *farm* layer on top of ghost: accounts bound to devices, a
day-by-day warming policy with hard caps, humanised input, four skills
(`ofmai_instagram`, `ofmai_tiktok`, `ofmai_x`, `ofmai_reddit`) and a planner
that turns the policy into ghost jobs. Ghost's core carries three small additive
changes, each listed and justified under *Divergences from upstream* below;
everything else is untouched, so upstream merges stay clean.

The operating rules (why Android, one account = one device = one IP, US
proxies, what a day of warming looks like) live in the OFMAI repo under
`docs/social/`. This file is the code map.

## Map

| Path | What |
|---|---|
| `gitd/farm/human.py` | `SessionProfile` (one motor signature per session) + `HumanInput`: tap with tremor and hold, feed swipes with drift and variable speed, per-character typing with typos, log-normal pauses and watch times |
| `gitd/farm/policy.py` | phases (consume → light → network → cruise, +3 days each on TikTok), `DailyBudget` (40–100 % of the caps, seeded per account and day, one rest day a week), `BudgetTracker` (caps + like/view ≤ 15 %, follow/visit ≤ 30 %), `plan_sessions` (2–4 sessions, drifting windows, never 01–07), health state machine |
| `gitd/farm/health.py` | on-screen signals per platform: action block, verification, logged out, suspended; zero-reach heuristic |
| `gitd/farm/models.py` · `ledger.py` | `farm_accounts`, `farm_actions`, `farm_signals`; additive columns (`role`, `market`, `ofmai_account_id`, `paused_until`) applied idempotently by `init()`; `open_session()` refuses unhealthy, paused or drifted accounts and records every counted action |
| `gitd/farm/devices.py` | is the phone attached, and is its system timezone still the one the ledger plans in (R20)? ADB injected as a function, so it is testable without a phone |
| `gitd/farm/warm.py` | the session loop, platform-agnostic, driven through a `PlatformAdapter` |
| `gitd/farm/skillkit.py` | `WarmSessionAction`: glue between a ghost workflow and the loop; `clock()` gives every workflow a virtual clock under `FARM_FAST=1` |
| `gitd/farm/planner.py` | every minute, enqueue due sessions as `skill_workflow` jobs, plus the answering passes that follow them (`comment_reply`, then `dm_reply` where the platform has messages) with the reply pools the bridge cached; idempotent via `farm_planned`, never on a phone that is still busy; skips api-mode, unhealthy, paused, `brand` and skill-less platforms. Publications are not planned here: OFMAI decides them and the bridge enqueues them from the queue item's `format` |
| `gitd/farm/cli.py` | `python -m gitd.farm.cli …` |
| `gitd/farm/alerts.py` | the fork's own Discord line (R32): `notify(level, title, message)` and `checkpoint_awaiting_human(...)`. Webhook from `FARM_DISCORD_WEBHOOK_URL`, else the keychain entry `ofmai-discord-webhook`. Only for what does not travel through OFMAI — a human gate, a dead bridge, a hand-typed kill-switch. Never raises, never blocks |
| `gitd/farm/signup.py` | account creation: where the four `recorded.json` live, the rules they must obey (`validate_steps`, `validate_params`), the two screens that stop a creation dead (`guard_screen`: a suspension, an identity check), and `GuardedRecordedWorkflow`. `python -m gitd.farm.signup` lints the four lists without a phone |
| `gitd/skills/ofmai_instagram/` | `warm_session`, `post_video` (Reel), `post_photo` (feed), `post_story` (spends `story_post`, never the weekly `post` cap), `comment_reply`, `dm_reply` |
| `gitd/skills/ofmai_tiktok/` | `warm_session`, `post_video` — the AI-label toggle follows `params.aigc_label` and is verified on screen before publishing —, `comment_reply`, `dm_reply` |
| `gitd/skills/ofmai_x/` · `ofmai_reddit/` | `warm_session` and `comment_reply`: both publish through their APIs, never from the device, and neither answers a DM (no automatic reply in V1). Reddit never votes back |
| `gitd/skills/ofmai_signup_{instagram,tiktok,x,reddit}/` | one recorded skill per platform: create the account by email, stop at every human gate (email code, password, captcha, SMS, identity), end on the profile screen showing the handle. `kind: hard`, `health_platform` set, `tested_on: []` |
| `scripts/farm_adb_connect.sh` · `farm_preflight.sh` · `farm_backup.sh` · `launchd/` | keep the phones attached, say whether the farm may run, back the ledger up, survive a reboot |
| `tests/test_farm_*.py` | unit tests, no device needed: `sh scripts/farm_tests.sh` |

## Daily use

```sh
# register an account: day 1 = today unless --created-on is given
python -m gitd.farm.cli accounts add instagram @eva.moore --device R58N1234 --tz America/New_York --niche "fitness,ootd,gymgirl"
python -m gitd.farm.cli accounts add x @eva_moore --device R58N1234 --role persona --market US --ofmai-id sa_01
python -m gitd.farm.cli accounts list
python -m gitd.farm.cli devices list                     # what `adb devices` sees
python -m gitd.farm.cli devices check                    # per account: online, timezone, aligned
python -m gitd.farm.cli budget instagram @eva.moore      # today's caps and what was spent
python -m gitd.farm.cli plan instagram @eva.moore        # today's session times
python -m gitd.farm.cli run instagram @eva.moore --minutes 3   # one session now (through ghost's runner)
python -m gitd.farm.cli daemon                           # the planner, next to `python3 run.py`

sh scripts/farm_preflight.sh                             # may the farm run right now?
sh scripts/farm_adb_connect.sh                           # reattach any phone that dropped off
```

Five platforms are accepted: `instagram`, `tiktok`, `x`, `reddit`, and
`telegram` (registered for later — no skill answers for it, so the planner never
schedules it). A `--role brand` account is created disabled and is never warmed;
the observer phone is refused outright, because it must never be warmed at all —
its serial lives in `FARM_OBSERVER_DEVICE`.

Sessions also appear in ghost's Scheduler tab (trigger `farm`) with logs and
a `Data: {...}` summary (videos, likes, follows, comments, detours, health).

## What the session does

Opens the app with human pacing, goes to Reels / For You / the timeline / the
Home feed, then until the minutes are up: watch (log-normal, with quick skips
and lingers), maybe like, maybe save, maybe open the author's profile and
follow, maybe comment from the supplied pool, take a detour every 12–30 items
(niche search; Instagram stories too), sometimes put the phone down for
20–90 s. Every counted action asks the ledger first. Any health signal on
screen ends the session and moves the account to cooldown / verification /
suspended; the planner then stops scheduling it until a human clears it
(`accounts clear-health`).

The primitive names come from the video feeds, but each skill maps them to its
own surface: a "view" is a Reel, a TikTok, an X post card or a Reddit post card;
`like` is the heart, or the upvote; `save` is Save, Favorites or Bookmark;
`follow` is Follow, or joining the post's community — and it only ever happens
after a profile visit, under the day's cap, never in bulk. Reddit never casts a
downvote and never votes back at anyone.

## Creating an account

One account per platform per phone, one platform per day, a human present for
the whole window. The procedure is `docs/social/account-creation.md` §6; here is
only what the code does.

```sh
# 1. before anything: do the rules still hold, and has Skill Miner been there?
PYTHONPATH=. python -m gitd.farm.signup          # exit 0 = the step lists are legal
                                                 # "NOT ready" until tested_on is filled (R34)

# 2. run it — detached, never through POST /api/skills/{name}/run (jobs die at 3600 s,
#    an SMS gate may wait longer). The password is NOT here: it is typed at a gate.
PYTHONPATH=. python -u gitd/skills/_run_skill.py \
  --skill ofmai_signup_instagram --workflow recorded --device R58N1234 \
  --params '{"email":"sierra.cole.ai@gmail.com","handle":"sierra.cole","name":"Sierra Cole",
             "birthday":"2001-03-14","bio_line1":"sierra, 25, la",
             "bio_line2":"AI character, made on ofmai","bio_line3":"6am club"}'

# 3. at each gate: the terminal prints AWAITING HUMAN, Discord gets the same line
#    with the phone and the resume command. Act on the device, then:
curl -X POST http://127.0.0.1:5055/api/skills/runs/<id>/resume \
     -H 'Content-Type: application/json' -d '{"action":"resume"}'

# 4. the same day, on the Mac mini — the skill never writes to the ledger:
PYTHONPATH=. python -m gitd.farm.cli accounts add instagram @sierra.cole \
  --device R58N1234 --tz America/Los_Angeles --created-on 2026-09-21
```

A gate resolves on whichever comes first: the human's `resume`, or the screen
condition appearing on its own. All of them have `timeout_s: 0` — a 600 s
timeout would leave a half-created account nobody owns.

Two screens end a run instead of pausing it (`guard_screen`): a suspension
(`health.py`'s `suspended` patterns — 30 days of quarantine for that phone) and
a request for a video selfie or an ID (§9: a synthetic character has no identity
to show). The other `health.py` kinds are deliberately *not* matched here:
"create new account", "verify your email", "drag the slider" are the normal
screens of a signup, and a guard that stopped on them would stop every run on
its first step.

## Selectors are not verified yet

`elements.yaml` in all four warming skills comes from en-US accessibility labels and
ghost's public TikTok ids. First thing on the Mac mini: run Skill Miner on
each app, fix the ids, run `warm_session` with `--minutes 2` while watching
the live stream, then fill `tested_on` in `skill.yaml`. Content-desc first,
resource-id second, coordinates never. The same goes for the health patterns
of X and Reddit: they are written from the strings those apps show today and
have not been seen on a device.

The four `ofmai_signup_*` skills are in the same state, and say so in code:
every step carries `"verified": false`, and `signup.ready_for_real_run(platform)`
returns False while any of them does or while `tested_on` is empty. Flip the
flags screen by screen as Skill Miner confirms them — the creation screens are
where a wrong selector is most expensive, because the button next to the right
one is a phone number, a follow, or an identity check.

## Divergences from upstream — écarts par rapport au dépôt amont

Everything the farm adds lives in `gitd/farm/` and `gitd/skills/ofmai_*`, which
upstream does not have. Three changes could not: they are listed here so that
the day we sync with upstream, nobody re-introduces a bug by silently taking
their version of these hunks. All three are additive and inert by default — a
skill that does not ask for them behaves exactly as it did, and a test proves it.

| # | File · what | Why it could not live anywhere else | Inert-by-default test |
|---|---|---|---|
| 1 | `gitd/skills/base.py` · `RecordedStepAction._run_checkpoint`, callback `_notify`: after the terminal line, fire `farm.alerts.checkpoint_awaiting_human` on a **daemon thread** | `_notify` is the only place that knows a run just entered `awaiting_human`. `run_checkpoint` receives it as an injected callback and the engine is the one that builds it; a farm-side wrapper would have had to re-implement the whole checkpoint dispatch. The thread is what guarantees R32 never costs the gate anything: no webhook, dead network, slow Discord — the human in front of the captcha is not made to wait | `test_farm_signup.py::test_a_checkpoint_without_a_webhook_is_not_delayed_by_discord`, plus the whole of `test_farm_alerts.py` |
| 2 | `gitd/skills/base.py` · `RecordedWorkflow.steps()`: `{placeholder}` substitution extended from `text/package/description/goal/prompt` to the string values of a step's `success` condition (new helper `_substitute`) | **This is an upstream bug, not an OFMAI need.** A checkpoint that waits for a screen derived from a parameter — `{"screen_has": "{handle}"}` — compares the literal string `{handle}` to the UI dump and can never auto-resolve, for anyone. Every signup skill ends on exactly such a gate. The substitution happens inside `steps()`, before the step dict reaches `RecordedStepAction`; there is no seam outside it | `test_farm_signup.py::test_a_success_condition_without_a_placeholder_is_left_alone` (unchanged) and `::test_a_success_condition_with_a_placeholder_is_resolved` (fixed) |
| 3 | `gitd/skills/_run_skill.py` · recorded path: `skill.yaml` is read before the workflow is built, and a `health_platform` key selects `farm.signup.GuardedRecordedWorkflow` instead of `RecordedWorkflow` | `_run_skill.py` is the documented launcher for a creation (`account-creation.md` §4.1 — never `POST /api/skills/{name}/run`, whose jobs die at 3600 s while an SMS gate may wait longer). The screen guard has to wrap the workflow at construction, and that is the only place a recorded skill is constructed | `test_farm_signup.py::test_no_upstream_or_warming_skill_asks_for_the_guard` — only the four `ofmai_signup_*` declare the key |

Change 2 is worth proposing upstream as-is; the other two are ours.

## Bench dry run without a phone

```sh
FARM_FAST=1 PYTHONPATH=. python -m pytest tests/test_farm_skills.py -q
```

`FARM_FAST=1` also gives the posting workflows a virtual clock, so a publish
can be rehearsed against a scripted screen without waiting out its pauses.

## Not done yet (next)

- OFMAI bridge: content queue (S3 keys + captions per character), comment
  pool per persona, events back to OFMAI
- collective health rules, machine kill-switch; Discord alerts exist for human
  gates only (`gitd/farm/alerts.py`) — the bridge and the kill-switch still have
  to call `notify()`
- shadowban canaries from the observer phone, metric pulls
- Portal companion app for faster UI reads on the farm phones
