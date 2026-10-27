# agent-setup

The parts of my Claude Code and Codex setup that I'd hand to another engineer: three skills, a browser tool, a guard hook with its tests, and the two scripts that keep every harness reading the same skills and MCP servers. I run agents unattended most of the day and I don't trust them, so most of what's here exists because something went wrong once.

This is a copy of a private repo, built from an allowlist by a script that redacts names and refuses to publish if anything private gets through. The layout mirrors `~/.agents` on my machine, so the paths inside the skills are the real ones.

## What's here, and what each piece prevents

### `mods/rule-guard`: rules that the model can't talk its way past
A Claude Code mod that turns rules from my global `AGENTS.md` into tool-call denials. A rule written in a prompt is a request; this hook is the control.

- From a personal project, it blocks pushes, PRs and API writes that land on a work repo (by GitHub owner, or by a path under `~/Projects`), including `git -C ../../work-repo push` and `cd ~/Projects/x && git push`.
- Personal repos commit as one noreply address. Any other commit email (`git config`, `-c user.email`, `GIT_*_EMAIL`, `--author`) is denied unless my prompt names the identity change.
- `git worktree add` is denied outside `<repo>/.worktrees`, `.claude/worktrees` or `~/.codex/worktrees`.
- In personal projects, cloud CLIs (aws, gcloud, vercel, terraform and 12 more, matched only in command position) need my explicit approval in the latest prompt. "Don't deploy" doesn't count as approval; the negation check has its own test.
- zsh reads `"$VAR:l"` as a lowercase modifier, so the hook rewrites `"$VAR:tag"` to `"${VAR}:tag"` before Bash runs it.

Tests: `claude plugin test mods/rule-guard` runs 25 tests in 2 files (pure rules, plus the hook driven through a fake session). All 25 passed on Claude Code 2.1.311 on this exact copy, with the work org renamed to the fictional `AcmeCorp`. `tsconfig.json` extends `.claude-plugin/types/`, which Claude Code generates when it loads the mod, so it isn't committed.

### `skills/knowledge-manager`: where a lesson goes, so the next agent finds it
One layout for every repo: hard rules in `AGENTS.md` (40 lines max), how things work in `docs/<area>.md`, rules learned the hard way in `lessons/`, dated events in `history/`, helpers in `scripts/`. Any agent finds a fact by grep instead of rereading the whole repo. The priority line is "accurate > concise > caps": a cap never deletes a fact.

- `scripts/audit.py <repo>`: read-only audit of a repo's agent context (cap breaches, missing frontmatter, malformed history lines, stale helpers). It never opens secret-shaped files.
- `scripts/conserve.py <ledger.json>`: when an agent reorganizes notes, every date, number, path and URL in the old text has to reach a destination, or be excused with a reason. Agents summarizing away facts is the failure this catches.
- `scripts/review.py <items.json>`: a local approve/reject page (127.0.0.1 only) for the changes that need a human.

### `skills/custom-browser-control` and `tools/`: browser agents that share my desktop
`tools/browser.py` drives an isolated Chrome over CDP with Playwright. Three of its rules, each with the incident behind it:

- One Chrome per profile. `get_browser()` finds a running instance from Chrome's own `SingletonLock` and attaches instead of launching a second one. Picking another port to "fix" a busy profile is what used to fail as `Chrome CDP port 93xx not ready after 15.0s`.
- Throwaway profile clones are garbage-collected. Nine leaked clones, each a full copy of the real profile including cookies, took 12 GB before this existed.
- Only the process that launched Chrome may close it. One that merely attached detaches, so it can't kill the browser under another agent.

`tools/chrome_hide.py` hides a headed Chrome with a real macOS app hide, targeted by PID. The usual trick, `--window-position=4000,4000`, put a "hidden" window on my second monitor (2026-08-30). `tools/chrome_reaper.py` closes automation Chromes that have had no CDP client for 5 minutes: on 2026-09-23 a 27-hour orphan on port 9300 was swallowing my Dock clicks and link opens, because macOS hands them to the older Chrome. macOS only for those two.

Setup: `pip install playwright` (and optionally `playwright-stealth`), put this repo's root on `PYTHONPATH`, then `from tools.browser import get_browser`. Environment knobs: `CLAUDE_BROWSER_PROFILE`, `CLAUDE_BROWSER_STATIC_DIR`, `CLAUDE_BROWSER_IDLE_TIMEOUT`, `CLAUDE_BROWSER_STEALTH`.

### `skills/app-development-guardrails`
Checklists for app runs where the failure is environment state rather than code: Flutter/Android over ADB, flaky UI automation, API contract mismatches. `scripts/android_focus_preflight.sh` checks which window has focus, and whether the system UI or lock screen is in front, before ADB taps go nowhere.

### `sync-skills.sh` and `mcp/sync.sh`: one source, every harness
- `sync-skills.sh`: `~/.agents/skills` is the single skill source. Codex reads it directly, Claude Code gets one symlink per skill in a real `~/.claude/skills`, Antigravity gets it registered. The real directory matters: skills Claude Code syncs from claude.ai stay Claude-only instead of leaking into the other harnesses through the shared source.
- `mcp/sync.sh`: one registry (`~/.agents/mcp/servers.json`) written into Codex, Claude Code, Antigravity, VS Code/Copilot, Cursor and Hermes. Env values come from an env file or `launchctl getenv`, and a server with a missing variable is skipped with a message instead of half-registered.

## What isn't here
My global rules, memory, scheduled jobs, profiles, per-project state and anything that names an account. The context-cost settings from [88% of my coding agent's usage goes on reading](https://denzil10.github.io/blog/the-model-rereading-itself/) live in my Claude Code settings and another mod, not in this repo; the post has the numbers and the settings.

MIT licensed: copy, adapt, ship.

— [Denzil Nelson](https://denzil10.github.io/) · [blog](https://denzil10.github.io/blog/) · [agent fleet](https://denzil10.github.io/agent-fleet/)
