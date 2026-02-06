# skills.sh Listing Guide

This project is listed on skills.sh through the **Skills CLI telemetry**, not through an npm package or manual registry submission. The skills leaderboard is driven by anonymous install telemetry from `npx skills add`.

## What You Need

- A public GitHub repository that contains your skill definition (e.g., `SKILL.md`) and a README explaining usage. Skills are hosted in GitHub repos.
- Clear installation instructions that tell users to install via the Skills CLI (`npx skills add <owner/repo>`).

## How Listing Works

- The leaderboard is powered by **anonymous install telemetry** from the Skills CLI.
- Once users install your skill with `npx skills add <owner/repo>`, it will show up and climb the ranking based on install counts.
- Telemetry can be disabled by users (`DISABLE_TELEMETRY=1`), so only installs with telemetry enabled contribute to leaderboard counts.

## Recommended README Snippet

Include this in your README so users install the skill the “right” way for listing:

```bash
npx skills add vaddisrinivas/voltsnip/voltsnip-skill
```

## Notes

- Publishing an npm package is **optional** and does not affect skills.sh ranking. (Skills are indexed through Skills CLI telemetry from GitHub installs.)
