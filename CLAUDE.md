# Ghost in the Droid — Agent Tool Rules

## MCP Tool: open_camera

For ANY task involving taking a photo, selfie, video, or opening the camera:

1. Load the tool: `ToolSearch({"query": "select:mcp__android-agent__open_camera"})`
2. Call it: `mcp__android-agent__open_camera(device=<serial>, mode=<mode>, timer_s=<seconds>)`

**modes:** `photo` (rear photo), `video` (rear video), `selfie` (front photo), `selfie_video` (front video)  
**timer_s:** `0` (off), `2`, `3`, `5`, `10`

This single call opens the correct camera mode AND sets the timer. Do NOT:
- use `launch_app` for camera tasks
- check `list_skills` for a camera skill
- tap camera UI manually to switch modes or set timers

## MCP Tool: speak_text

To make the phone speak text aloud:

1. `ToolSearch({"query": "select:mcp__android-agent__speak_text"})`
2. `mcp__android-agent__speak_text(device=<serial>, text="...", rate=1.0)`

Works from PC and on-device — always emits audio from the phone.

## General rule

All `mcp__android-agent__*` tools are already loaded by the MCP server. To use any of them:
`ToolSearch({"query": "select:mcp__android-agent__<tool_name>"})` then call it directly.

## OFMAI farm — machine M1 (armée de personnages)

Le cahier des charges complet (règles, architecture, GeeLark + proxies, création de comptes, chauffe, contenu, publication, santé, pont OFMAI ↔ ferme, attribution, personas, plan de construction) vit dans `docs/social/` : commencer par `docs/social/INDEX.md`, puis `docs/social/00-brief-decisions.md` (les décisions prises avec Nathan). `gitd/farm/policy.py` reflète `docs/social/warming-policy.md`. Le repo OFMAI (plateforme) est un projet séparé ; les endpoints côté OFMAI décrits dans `docs/social/bridge-ofmai-farm.md` s'implémentent là-bas.
