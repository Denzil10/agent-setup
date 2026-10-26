# Templates

Caps are ceilings, not targets. Accuracy wins over every cap.

## Frontmatter (every `docs/*.md`, `lessons/*.md`, `local/tasks/lessons/*.md`)

```
---
summary: one line, what this file answers
when: situations that need it (editing payments, debugging webhook retries)
paths: code globs it covers (src/payments/**, api/webhooks/*)
updated: YYYY-MM-DD
---
```

`paths:` may be empty for life areas with no code. Doc cap ~150 lines; split along area lines.

## Lesson entry (local and team identical, so promotion is a move)

```
## YYYY-MM-DD — When <situation the next agent will be in>
Rule: what to do.
Why: verified cause or evidence.
Seen: YYYY-MM-DD, YYYY-MM-DD        (optional; recurrence)
```

Cap: 3 lines plus `Seen:`. ~30 entries per area file; over that, merge and drop superseded ones.

## History line (`history/YYYY.md`, append-only, never rewritten)

```
YYYY-MM-DD · <area> · incident|decision|external|milestone · what happened; outcome → lessons/<area>.md
```

One line, ~200 chars. Only what git log doesn't already record. File starts with `# History YYYY` and no frontmatter.

## Helper header (first comment or docstring lines of a kept script)

```
# summary: what it does, in one line
# run: python3 scripts/<area>/<name>.py <args>
```

## Repo AGENTS.md skeleton (≤40 lines)

```
# <repo>
<one line: what it is, who uses it>

## Run
<install, dev, test, deploy commands>

## Rules
- <repo-wide hard rule> (only rules that apply everywhere in the repo)

## Find context
Before working in an area: `grep -rH '^summary:\|^paths:' docs lessons scripts`
"Happened before?" / "why is it like this?": `grep -rn <area> history/`
Personal lessons: `local/tasks/lessons.md` (gitignored).
```
