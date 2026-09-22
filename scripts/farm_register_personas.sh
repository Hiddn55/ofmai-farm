#!/usr/bin/env sh
# Register the six personas' Reddit accounts in the farm ledger, on the Mac mini.
#
# Run ONCE, the day the accounts exist (docs/social/account-creation.md §7):
# from `accounts add` on, the planner schedules that account's sessions and
# nobody touches the app by hand any more. Registering an account that does
# not exist yet would make the daemon open Reddit on a phone with no login.
#
# The explorer account (jordan_reed97 on `explorer-us`) is NEVER registered:
# it exists to mine screens and replay gestures, out of the warming calendar.
#
# Columns — fill the table before running; the script refuses a placeholder:
#   handle   the Reddit username the signup skill ended on (persona sheet,
#            `accounts.reddit.handle` — only sierra's is written down so far)
#   device   the GeeLark profile name (gitd/farm/devices.py resolves it to
#            the ADB serial at session time: the port changes on every start)
#   tz       the persona's timezone = the PROXY's city, not the wish of
#            personas.md §3.2 (infrastructure-geelark-proxies.md §4: the
#            sheet is aligned on the address bought, never the other way);
#            the seven addresses bought on 2026-09-17 sit in Seattle (x2),
#            Chevy Chase MD, Overland Park KS, Houston TX and Springfield —
#            set each line from the address actually attached to the profile
#   niche    comma-separated hashtags (`niche.hashtags_niche` of the sheet):
#            the fallback of the search detours
#   ofmai    the OFMAI SocialAccount id, once the account exists on ofmai.ai
#
# Usage:  scripts/farm_register_personas.sh <YYYY-MM-DD of creation>
cd "$(dirname "$0")/.." || exit 1
PY="${PY:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
CREATED="${1:?usage: $0 <YYYY-MM-DD of the Reddit accounts creation>}"

# slug          handle              device      tz                    niche (hashtags)           ofmai SocialAccount id
TABLE='
sierra         sierra_cole_ai      sierra-us   America/Los_Angeles   fitness,gym,fitcheck       <ofmai-id>
camila         <handle>            camila-us   <tz>                  latina,miami,ootd          <ofmai-id>
hana           <handle>            hana-us     <tz>                  skincare,minimal,seoul     <ofmai-id>
skyler         <handle>            skyler-us   <tz>                  bimbo,glam,pink            <ofmai-id>
riley          <handle>            riley-us    <tz>                  egirl,gaming,setup         <ofmai-id>
vera           <handle>            vera-us     <tz>                  goth,alt,darkacademia      <ofmai-id>
'

if printf '%s' "$TABLE" | grep -q '<handle>\|<tz>'; then
    echo "farm_register_personas: fill every <handle> and <tz> in the table first (the Reddit username the signup ended on, and the proxy city's timezone)." >&2
    exit 2
fi

printf '%s\n' "$TABLE" | while read -r slug handle device tz niche ofmai; do
    [ -z "$slug" ] && continue
    extra=""
    if [ -n "$ofmai" ] && [ "$ofmai" != "<ofmai-id>" ]; then
        extra="--ofmai-id $ofmai"
    fi
    # shellcheck disable=SC2086 — $extra is either empty or one flag and its id
    PYTHONPATH=. "$PY" -m gitd.farm.cli accounts add reddit "@$handle" \
        --device "$device" --tz "$tz" --created-on "$CREATED" \
        --character "$slug" --niche "$niche" --role persona --market us $extra || exit 1
done

PYTHONPATH=. "$PY" -m gitd.farm.cli accounts list
