#!/usr/bin/env python3
"""summary: read-only audit of one repo's agent context against the knowledge-manager structure.
run: python3 audit.py <repo> [--json]

Reports cap breaches, missing frontmatter, oversize lesson entries, malformed history lines,
kept helpers without a `summary:` line, stale local/ helpers and nested AGENTS.md.
Reads only .md files and the first lines of code files; never opens secret-shaped files.
"""
import json, os, re, sys, time
from pathlib import Path

SKIP = {".git", "node_modules", ".venv", "venv", "vendor", ".next", "dist", "build", ".worktrees",
        "__pycache__", "site-packages", "target", ".dart_tool", "Pods", "keys"}
DENY = re.compile(r"(^\.env|secret|password|credential|keychain)", re.I)
CODE = {".py", ".sh", ".js", ".mjs", ".ts", ".rb", ".swift"}
CAPS = {"agents_lines": 40, "doc_lines": 150, "lesson_entries": 30, "entry_lines": 3, "history_chars": 200}
STALE_DAYS = 30
HISTORY = re.compile(r"^\d{4}-\d{2}-\d{2} · [\w./-]+ · (incident|decision|external|milestone) · .+")


def files(root, sub, exts, depth=6):
    base = root / sub
    if not base.is_dir():
        return []
    out = []
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".")]
        if len(Path(dp).relative_to(base).parts) >= depth:
            dns[:] = []
        out += [Path(dp) / f for f in fns if Path(f).suffix in exts and not DENY.search(f)]
    return out


def front(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M)) if m else None


def entries(text):
    """`## ` sections with their non-blank body lines, `Seen:` excluded."""
    out = []
    for part in re.split(r"(?m)^(?=## )", text)[1:]:
        lines = part.splitlines()
        body = [l for l in lines[1:] if l.strip() and not l.startswith("Seen:")]
        out.append((lines[0][3:].strip(), len(body)))
    return out


def audit(root):
    f = []  # (kind, path, detail)
    rel = lambda p: str(p.relative_to(root))
    agents = root / "AGENTS.md"
    if agents.resolve() == (Path.home() / ".agents/AGENTS.md").resolve():
        pass  # the setup repo: its AGENTS.md is the global file, linked as ~/.claude/CLAUDE.md; repo caps don't apply
    elif not agents.exists():
        f.append(("missing", "AGENTS.md", "no root AGENTS.md"))
    else:
        n = len(agents.read_text(errors="ignore").splitlines())
        if n > CAPS["agents_lines"]:
            f.append(("cap", "AGENTS.md", f"{n} lines > {CAPS['agents_lines']}"))
        if not (root / "CLAUDE.md").exists():
            f.append(("missing", "CLAUDE.md", "no CLAUDE.md link to AGENTS.md (Claude Code reads CLAUDE.md)"))
    for p in files(root, ".", {".md"}):
        if p.name in ("AGENTS.md", "CLAUDE.md") and p.parent != root and "local" not in p.relative_to(root).parts:
            f.append(("nested", rel(p), "nested agent file (new ones deferred; keep folder-only rules)"))
    for p in files(root, "docs", {".md"}):
        t = p.read_text(errors="ignore")
        if front(t) is None or "summary" not in (front(t) or {}):
            f.append(("frontmatter", rel(p), "no frontmatter summary"))
        n = len(t.splitlines())
        if n > CAPS["doc_lines"]:
            f.append(("cap", rel(p), f"{n} lines > {CAPS['doc_lines']}"))
    for sub in ("lessons", "local/tasks/lessons"):
        for p in files(root, sub, {".md"}):
            t = p.read_text(errors="ignore")
            if front(t) is None or "summary" not in (front(t) or {}):
                f.append(("frontmatter", rel(p), "no frontmatter summary"))
            es = entries(t)
            if len(es) > CAPS["lesson_entries"]:
                f.append(("cap", rel(p), f"{len(es)} entries > {CAPS['lesson_entries']}"))
            for h, n in es:
                if n > CAPS["entry_lines"]:
                    f.append(("entry", rel(p), f"'{h[:60]}' {n} lines > {CAPS['entry_lines']}"))
    lm = root / "local/tasks/lessons.md"
    if lm.exists():
        es = entries(lm.read_text(errors="ignore"))
        if len(es) > CAPS["lesson_entries"]:
            f.append(("cap", rel(lm), f"{len(es)} entries > {CAPS['lesson_entries']}; route to area files"))
        f += [("entry", rel(lm), f"'{h[:60]}' {n} lines > {CAPS['entry_lines']}") for h, n in es if n > CAPS["entry_lines"]]
    for p in files(root, "history", {".md"}):
        for i, l in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if not l.strip() or l.startswith("#"):
                continue
            if not HISTORY.match(l):
                f.append(("history", f"{rel(p)}:{i}", "not `date · area · type · text`"))
            elif len(l) > CAPS["history_chars"]:
                f.append(("history", f"{rel(p)}:{i}", f"{len(l)} chars > {CAPS['history_chars']}"))
    for p in files(root, "scripts", CODE):
        with p.open(errors="ignore") as h:
            head = "".join(l for _, l in zip(range(6), h))
        if "summary:" not in head:
            f.append(("helper", rel(p), "kept helper without `summary:` line"))
    docs_text = " ".join(p.read_text(errors="ignore") for p in files(root, "docs", {".md"}))
    cutoff = time.time() - STALE_DAYS * 86400
    for p in files(root, "local", CODE):
        if p.stat().st_mtime < cutoff and p.name not in docs_text:
            f.append(("stale", rel(p), f"local helper untouched {STALE_DAYS}+ days, not referenced in docs/"))
    return f


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: audit.py <repo> [--json]")
    root = Path(args[0]).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"{root}: not a directory")
    found = audit(root)
    if "--json" in sys.argv:
        json.dump([{"kind": k, "path": p, "detail": d} for k, p, d in found], sys.stdout, indent=1)
        return
    if not found:
        print(f"{root}: clean")
        return
    print(f"{root}: {len(found)} findings")
    for kind in ("missing", "cap", "entry", "frontmatter", "history", "helper", "nested", "stale"):
        rows = [(p, d) for k, p, d in found if k == kind]
        if rows:
            print(f"\n{kind} ({len(rows)})")
            for p, d in rows[:40]:
                print(f"  {p}: {d}")
            if len(rows) > 40:
                print(f"  ... {len(rows) - 40} more")


if __name__ == "__main__":
    main()
