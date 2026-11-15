# pstack model configuration for Codex

User-confirmed project-local adaptation of cursor/plugins setup-pstack, 2026-11-01.
This document is configuration guidance, not an installed Cursor rule or automatic model router.

budget: small (medium target). inherit-parent preserves the active model and effort; it does not enforce medium.

| Role | Model |
|---|---|
| feature, refactoring | inherit-parent |
| bug-fix | inherit-parent |
| perf-issue | inherit-parent |
| hillclimb | inherit-parent |
| judgment and prose | inherit-parent |
| hardest tasks | inherit-parent |
| how explorer | inherit-parent |
| how explainer | inherit-parent |
| why investigators | inherit-parent |
| why synthesizer | inherit-parent |
| reflect tooling | inherit-parent |
| reflect judgment, divergent, synthesizer | inherit-parent |
| arena runners | [inherit-parent] |
| arena cross-judge pool | [] |
| swarm workers | inherit-parent |
| architect runners | [inherit-parent] |
| interrogate reviewers | [inherit-parent] |

No pre-existing global rule was found. No retired role lines were removed. Parent aliases are not eligible cross-judges. No global Cursor files were changed.
