#!/usr/bin/env python3
"""summary: Init-mode conservation check: every fact token in each ledger source unit must reach one of its destinations.
run: python3 conserve.py <ledger.json> [--json]

Tokens = dates, numbers, ₹ amounts, backtick spans, paths, URLs. A source line may be excused only by an
`allowed` entry (`match` substring or `regex`) (deliberate correction or drop, with a reason) — those become review rows.
Prints unit IDs, source line numbers and counts only, never token text (sources can hold secrets).
Source specs: `git:<rev>:<path>[#<heading prefix>|@<a>-<b>]`, `file:<abs path>[@<a>-<b>]`.
`keep`/`delete`/`route` units are existence-checked only; `source` units (provenance for new facts, with `dest_claim`) must exist. Their content is never read.
"""
import json, re, subprocess, sys
from pathlib import Path

TOKEN = re.compile(
    r"`[^`\n]+`"
    r"|https?://[^\s)<>\"']+"
    r"|\d{4}-\d{2}-\d{2}"
    r"|₹\s?[\d,.]+[kKL]?"
    r"|(?<![\w.~/])(?:~/|\.{0,2}/)[\w.-]+(?:/[\w.*<>{}-]+)*/?"  # rooted paths
    r"|[\w.-]+(?:/[\w.*<>{}-]+)+\.\w{1,5}\b"  # relative paths with an extension
    r"|\d+(?:[.,:]\d+)*")


def norm(s):
    s = s.replace(" ", " ").replace(" ", " ").replace(" ", " ").lower()
    s = re.sub(r"[*_]{1,2}", "", s)
    return re.sub(r"\s+", " ", s)


def tokens(line):
    out = []
    for m in TOKEN.finditer(line):
        t = m.group(0).strip("`").rstrip(".,;:)")
        if re.fullmatch(r"\d", t):  # single digits: list markers, counts in prose
            continue
        out.append(norm(t))
    return out


def read_spec(spec, repo):
    rng = None
    if "@" in spec.split(":")[-1]:
        spec, r = spec.rsplit("@", 1)
        a, b = map(int, r.split("-"))
        rng = (a, b)
    head = None
    if spec.startswith("git:"):
        _, rev, path = spec.split(":", 2)
        if "#" in path:
            path, head = path.split("#", 1)
        text = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"],
                              capture_output=True, text=True, check=True).stdout
    elif spec.startswith("file:"):
        text = Path(spec[5:]).expanduser().read_text(errors="replace")
    else:
        raise SystemExit(f"bad source spec: {spec}")
    lines = text.split("\n")
    start = 1
    if head:
        i = next(n for n, l in enumerate(lines) if l.startswith(head))
        j = next((n for n in range(i + 1, len(lines)) if re.match(r"#{1,2} ", lines[n])), len(lines))
        lines, start = lines[i:j], i + 1
    if rng:
        lines, start = lines[rng[0] - 1:rng[1]], rng[0]
    return [(start + k, l) for k, l in enumerate(lines)]


def dest_text(dests, repo):
    out = []
    for d in dests:
        p = Path(d).expanduser()
        p = p if p.is_absolute() else repo / p
        if not p.exists():
            raise SystemExit(f"missing destination: {d}")
        out.append(p.read_text(errors="replace"))
    return norm("\n".join(out))


def check(unit, repo):
    act = unit["action"]
    if act in ("keep", "delete", "route", "source"):
        p = Path(unit["path"]).expanduser()
        ok = p.exists() if act in ("keep", "source") else True
        return {"id": unit["id"], "action": act, "ok": ok, "missing": []}
    lines = read_spec(unit["src"], repo)
    dest = dest_text(unit["dest"], repo)
    allowed = unit.get("allowed", [])
    missing, used = [], set()
    for n, line in lines:
        miss = [t for t in tokens(line) if t not in dest]
        if not miss:
            continue
        hit = next((k for k, a in enumerate(allowed)
                    if ("match" in a and a["match"] in line) or ("regex" in a and re.search(a["regex"], line))), None)
        if hit is not None:
            used.add(hit)
            continue
        missing.append({"line": n, "count": len(miss)})
    unused = [k for k in range(len(allowed)) if k not in used]
    return {"id": unit["id"], "action": act, "ok": not missing, "missing": missing, "unused_allowed": len(unused)}


def main():
    ledger = json.loads(Path(sys.argv[1]).read_text())
    repo = Path(ledger["repo"]).expanduser()
    res = [check(u, repo) for u in ledger["units"]]
    if "--json" in sys.argv:
        print(json.dumps(res, indent=1))
        return
    bad = [r for r in res if not r["ok"]]
    for r in bad:
        where = ", ".join(f"L{m['line']}({m['count']})" for m in r["missing"]) or "path missing"
        print(f"FAIL {r['id']} [{r['action']}]: {where}")
    for r in res:
        if r.get("unused_allowed"):
            print(f"note {r['id']}: {r['unused_allowed']} allowed entr(y/ies) matched nothing")
    print(f"{len(res) - len(bad)}/{len(res)} units conserved")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
