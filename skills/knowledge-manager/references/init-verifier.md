# Init: read-only verifier

After the place commit, run one independent verifier over the ledger and the diff:

```
command claude -p --model opus --tools Read Grep Glob --strict-mcp-config --permission-mode default --add-dir <snapshot> <repo>/local < verifier-prompt.txt
```

- `--allowedTools` does not take tools away under `bypassPermissions` (the user's `claude` alias and `claude-run` both bypass), and the Monitor tool ran a shell write in the 2026-10-17 pilot. Only `--tools … --permission-mode default` makes it read-only. Use `command claude` to skip the alias.
- Give it: repo path, base and head commits, the ledger path, and the never-open list. Ask for findings only (lost or changed facts, contradictions, wrong homes, boundary leaks), each with file and line.
- Fix confirmed findings in a follow-up commit; a finding the code or live state contradicts is dropped, not argued.
- Run it from the repo or worktree; under `default` it can only read cwd plus `--add-dir` paths. Without `--add-dir` it could not open the ledger or `local/` (2026-10-19 Init). `--add-dir` is variadic: pass the prompt on stdin, or it is read as a directory.
