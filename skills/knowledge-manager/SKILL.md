---
name: knowledge-manager
description: "Capture, place and organize agent knowledge (lessons, docs, history, helpers, memory) in any repo. Use when: (1) the user corrects you ('No, that's wrong', 'Actually...', 'that's outdated'); (2) a command, API or tool fails and you find the verified root cause; (3) you learn a fact you lacked or find a doc outdated; (4) you find a better approach for a recurring task; (5) the user asks for a capability that doesn't exist yet; (6) something worth a dated record happens (outage, incident, decision, vendor change, milestone); (7) the user asks to organize, consolidate, clean up or audit memory, lessons, docs or context; (8) initializing a repo's context (Pass 1) or harvesting findings from local/, session transcripts or Downloads; (9) before major work in an area, to read its lessons and history."
---

# Knowledge manager

One structure for every repo, so any agent (Claude, Codex, Antigravity) finds the right fact by grep.

**Priority: accurate > concise > caps.** Never cut, merge or summarize away a fact, number, condition or caveat to save space. Caps are ceilings, not targets: write the minimum that carries the point. If accurate content can't fit, exceed the cap and flag it.

**Keep bar:** keep only what would change a future decision or save real time. Everything else is deleted, not archived.

**Prune vs cut:** delete what is superseded or contradicted by live state, done and already recorded elsewhere, or a duplicate (keep the best copy). Compress = same facts in fewer words. Neither drops a live fact.

**Lifecycle:** (1) *Capture*, every session: search, then edit an existing entry or add one; never promote. (2) *Init*, once per repo: harvest, route into layers, prune. (3) *Weekly* (scheduled repos): verify against code, merge, compress, prune, promote; one batch of ≤10 cross-project questions.

**Agents decide.** Apply, commit, then report a short digest; git is the undo. Untracked content (`local/`) is moved instead of deleted: personal repos → `~/.home/other/backups/`; work repos → leave it in place and list it in the digest (never into `~/.home`). Ask the user only for: work↔personal boundary moves; deleting data that has no other copy; adding or dropping a global rule (rewording is fine); conflicts code or live state can't settle; irreversible or outward actions (pushes to shared remotes, external services).

## Where things go

| Item | Home | Loads |
|---|---|---|
| Repo-wide hard rule | `AGENTS.md` (≤40 lines; CLAUDE.md links to it) | every session |
| Area fact: how something works now | `docs/<area>.md` | grep |
| Area rule or quirk the team needs | `lessons/<area>.md` (committed) | grep |
| Personal or unvetted lesson | `local/tasks/lessons/<area>.md`, or `local/tasks/lessons.md` if no area | lessons.md at start |
| Dated event git doesn't record | `history/YYYY.md` (committed, append-only) | grep |
| Helper that runs again | `scripts/<area>/` (repo) or `~/.agents/bin` (cross-repo) | grep |
| One-off script | session scratchpad or `local/scratch/`; delete at close-out | — |
| Raw data, heavy output | local, gitignored, listed in `docs/local-assets.md` | — |
| Recurring procedure | skill (global only if ≥2 projects use it) | index always |
| Open item that outlives the session (user action, deferred work, idea, capability the user wants that doesn't exist); never in-session steps or progress, which stay in the harness task list | `local/tasks/todo.md` (one line, under its area; done → delete, plus a history line if it's a dated event) | — |
| User preference, account fact, external pointer with no repo home | Claude auto-memory | index always |
| Cross-project personal knowledge | context wiki `~/.home/self/context` (its AGENTS.md); never work knowledge | grep |
| Applies to every session | propose a global rule to the user; never edit global AGENTS.md mid-task | — |

- An **area** is a subject an agent would search for (`infra`, `payments`, `fitness`). `docs/infra.md`, `lessons/infra.md`, `scripts/infra/` and the `infra` history tag are one area. Create an area when its first real item appears.
- Lessons never go into docs. A fact learned through a lesson is written into the doc as a plain fact.
- A lesson that only records "this happened once" belongs in history. An event that taught a rule links to the lesson; neither repeats the other.
- Nested `AGENTS.md`: do not create new ones (decision deferred). Edit existing ones only for their folder.
- Life work that belongs to no repo lives in `~/.home/self/dashboard`.
- Formats (frontmatter, lesson entry, history line, helper header, AGENTS.md skeleton): [references/templates.md](references/templates.md).

## Capture (during any task)

Triggers, from the description: corrections, failures with a verified root cause, knowledge gaps, better approaches, missing capabilities, dated events.

1. **Search first.** `grep -rn '<keyword>' lessons local/tasks/lessons* docs history`. If an entry covers it, edit that entry (add a `Seen:` date) instead of adding a near-duplicate.
2. **Classify.**
   - Correction or verified root cause → lesson (local by default; team `lessons/` only when the repo's team needs it).
   - Error without a verified cause → `todo.md`, not a lesson. Guesses never become rules.
   - External one-off (outage, vendor change) → history line, plus a lesson only if it taught a rule.
   - Missing capability → `todo.md`.
   - Repo fact (how something works, area rule, event) → straight to its repo home above, never to Claude auto-memory. Claude memory takes only user preferences, account facts and external pointers with no repo home.
3. **Write the prevention rule, not the incident story.** Trigger = the situation the next agent will be in ("When editing launchd plists"). Absolute dates. Example:
   - Verbose: "Ran npm install, failed; lock file is pnpm-lock.yaml; must use pnpm."
   - Entry: `## 2026-10-17 — When installing deps in this repo` / `Rule: use pnpm install (pnpm-lock.yaml, workspaces).` / `Why: npm install fails on the workspace layout.`
4. **No secrets.** No tokens, keys, env values, full configs or raw command dumps; use short redacted excerpts.
5. **Log immediately**, while context is fresh; name the related files.

**Recurrence.** When the same lesson is seen a 3rd time across 2+ tasks within 30 days, a counter is not enough; fix it systemically: promote to team `lessons/` or `AGENTS.md`, add a hook or check, or extract a skill.

**Skill extraction** when a lesson is recurring, verified, non-obvious and broadly applicable, or the user says "save this as a skill". Gates: solution tested; self-contained without this conversation; no hardcoded project values; name is lowercase-hyphen and matches its folder; follows https://agentskills.io/specification.

## Review (before major work in an area)

```
grep -rH '^summary:\|^paths:' docs lessons scripts local/tasks/lessons 2>/dev/null
grep -rn '<area>' history/ 2>/dev/null
```

Open only the matching area files. Also review after finishing a feature (anything to capture?).

## Organize (on demand in any repo; weekly in scheduled repos)

1. Run `python3 <skill>/scripts/audit.py <repo>` (read-only). It lists cap breaches, missing frontmatter, oversize lesson entries, malformed history lines, helpers without `summary:`, stale `local/` helpers, nested AGENTS.md.
2. For each lesson and doc fact, check it against the code now. Live evidence beats memory: correct or delete what the code contradicts.
3. Prune per **Prune vs cut**, including done and superseded `todo.md` items. Merge duplicates into the best home; demote one-off lessons to history; move area facts out of lessons into docs; promote recurring local lessons to `lessons/<area>.md` (move the entry unchanged).
4. Add or fix frontmatter; split a doc that is over its cap only along area lines.
5. Edit small deltas; never rewrite a whole existing file (rewrites lose detail). Never delete a fact to meet a cap.
6. Measure tokens before and after as bytes/4 of the touched files (personal repos may also run `~/.home/self/dashboard/scripts/context-sizes.py`), and commit.
7. Report a digest: moved, merged, deleted, corrected, tokens before → after, and only the ask-list items above.

## Init (Pass 1, one repo at a time)

1. Read the repo's `AGENTS.md`/`CLAUDE.md`, `local/tasks/lessons*`, `docs/`, Claude memory dir, and run `audit.py`.
2. Pick the tier: **scheduled** (weekly pass) or **light** (on demand only), by the repo's role, not recent activity. Record it in the registry (`~/.home/self/dashboard/docs/context.md`).
3. Harvest (below), then route every item per the table.
4. Write `AGENTS.md` to the skeleton; move everything else into areas. Check the moves with `scripts/conserve.py` (every moved fact reaches its destination; delete units are recorded, not blocked), run one read-only verifier ([references/init-verifier.md](references/init-verifier.md)), fix confirmed findings, and commit.
5. As a separate commit, prune and compress (Organize steps 2–6), then report the digest. The user reviews only the ask-list items.

## Harvest (Init, and Organize in scheduled repos)

Sources, filtered to this repo only (match transcript `cwd` or project slug to the repo path):

1. Repo `local/`: reports, research, plans, scripts.
2. Transcripts: Claude `~/.claude/projects/<slug>/*.jsonl`, Codex `~/.codex/sessions/**` (by `cwd`), Antigravity `~/.gemini/antigravity-cli/brain/*` (by paths it touched).
3. `~/Downloads` and session scratchpads: personal repos only, items that clearly belong to this repo.

Extract conclusions, numbers, decisions, dated events and reusable helpers. Never copy transcripts. Each item ends as one of: doc fact, lesson, history line, helper, `local-assets.md` entry, or a delete-list line for the user.

**Never open:** `.env*`, `keys/`, files named `*secret*`, `*password*`, `*credential*`, account or bank exports (`*.xlsx`, `*.csv` with account/statement data), `keychain-secrets.txt`. Record that such a file exists if it matters; never its contents.

**Boundaries:** work (`~/Projects/*`) and personal (`~/.home/*`) knowledge never cross, in either direction. Personal or health data only goes to private repos: check visibility first (`gh repo view --json visibility`). Nothing personal in tracked files under `~/.home/public/`.
