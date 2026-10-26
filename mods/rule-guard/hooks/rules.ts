// Pure checks behind register.ts; each mirrors one rule in ~/.agents/AGENTS.md.

export type Zone = 'personal' | 'work' | 'other'

// Personal: ~/.home. ~/.home/setup (= ~/.agents) is shared, like ~/.agents.
export function zoneOf(dir: string): Zone {
  if (/^\/Users\/[^/]+\/\.home\/setup(\/|$)/.test(dir)) return 'other'
  if (/^\/Users\/[^/]+\/\.home(\/|$)/.test(dir)) return 'personal'
  if (/^\/Users\/[^/]+\/Projects\/[^/]+/.test(dir)) return 'work'
  return 'other'
}

export function resolve(path: string, cwd: string, home: string): string {
  const unq = path.replace(/^(['"])(.*)\1$/, '$2')
  const abs = unq.startsWith('~') ? home + unq.slice(1) : unq.startsWith('/') ? unq : `${cwd}/${unq}`
  const parts: string[] = []
  for (const p of abs.split('/')) {
    if (p === '' || p === '.') continue
    if (p === '..') parts.pop()
    else parts.push(p)
  }
  return '/' + parts.join('/')
}

// The directory a command acts in: `git -C <dir>`, else a leading `cd <dir> &&`, else cwd.
export function targetDir(command: string, cwd: string, home: string): string {
  const gitC = /\bgit\s+-C\s+("[^"]+"|'[^']+'|\S+)/.exec(command)
  if (gitC?.[1]) return resolve(gitC[1], cwd, home)
  const cd = /^\s*cd\s+("[^"]+"|'[^']+'|[^\s;&|]+)\s*(&&|;)/.exec(command)
  if (cd?.[1]) return resolve(cd[1], cwd, home)
  return cwd
}

// Commands that write to GitHub: pushes, PR/repo/release/issue writes, mutating API calls.
const REMOTE: readonly RegExp[] = [
  /\bgit\s+(?:-[Cc]\s+\S+\s+)*push\b/,
  /\bgh\s+pr\s+(?:create|merge|close|edit|comment|review|ready)\b/,
  /\bgh\s+repo\s+(?:create|delete|edit|rename|archive|fork)\b/,
  /\bgh\s+release\s+(?:create|delete|edit|upload)\b/,
  /\bgh\s+issue\s+(?:create|close|comment|edit|delete)\b/,
  /\bgh\s+api\b[^|;&\n]*(?:-X|--method)\s*(?:POST|PATCH|PUT|DELETE)\b/i,
]

export const isRemote = (command: string): boolean => REMOTE.some(re => re.test(command))

// The GitHub owner a remote URL names: git@github.com:o/r, https://github.com/o/r, ssh://git@github.com/o/r.
export function ownerOf(url: string): string | undefined {
  return /github\.com[:/]+([^/\s]+)\//i.exec(url)?.[1]
}

// Owners the command names itself: `-R/--repo o/r`, a GitHub URL, `gh api repos/o/...`, `gh repo create o/r`.
export function namedOwners(command: string): string[] {
  const found: string[] = []
  for (const re of [
    /(?:-R|--repo)[=\s]+["']?([\w.-]+)\/[\w.-]+/g,
    /github\.com[:/]+([\w.-]+)\/[\w.-]+/gi,
    /\bgh\s+api\s+(?:[^|;&\n]*\s)?\/?repos\/([\w.-]+)\//g,
    /\bgh\s+repo\s+(?:create|delete|edit|rename|archive)\s+([\w.-]+)\/[\w.-]+/g,
  ])
    for (const m of command.matchAll(re)) found.push(m[1]!)
  return found
}

// The remote a `git push` names (name or URL); undefined when it relies on the branch's push default.
export function pushRemote(command: string): string | undefined {
  const m = /\bgit\s+(?:-[Cc]\s+\S+\s+)*push\b([^;&|\n]*)/.exec(command)
  if (!m) return undefined
  const words = m[1]!.trim().split(/\s+/).filter(Boolean)
  for (let i = 0; i < words.length; i++) {
    const w = words[i]!
    if (w === '--') return words[i + 1]
    if (/^--repo=/.test(w)) return w.slice(7)
    if (['--repo', '-o', '--push-option', '--receive-pack', '--exec'].includes(w)) {
      if (w === '--repo') return words[i + 1]
      i++
      continue
    }
    if (w.startsWith('-')) continue
    return w.replace(/^(['"])(.*)\1$/, '$2')
  }
  return undefined
}

export const isWorkOwner = (owner: string | undefined, work: readonly string[]): boolean =>
  owner !== undefined && work.some(w => w.toLowerCase() === owner.toLowerCase())

const CLOUD =
  /(?:^|[;&|(`\n]|\$\()\s*(?:\w+=\S*\s+)*(?:(?:sudo|npx|bunx|exec|time|command)\s+(?:-\S+\s+)*)*(aws|gcloud|gsutil|bq|az|azd|doctl|firebase|vercel|flyctl|wrangler|heroku|railway|terraform|pulumi|eksctl)(?=$|[\s;&|)])/

export const cloudCli = (command: string): string | undefined => CLOUD.exec(command)?.[1]

// Did the user's latest prompt ask for this? Any of `words` present, no "don't/never [x y] <word>".
export function requested(prompt: string, words: readonly string[]): boolean {
  const alt = words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  if (new RegExp(`\\b(?:don'?t|do not|never|no)\\s+(?:\\w+\\s+){0,2}(?:${alt})\\b`, 'i').test(prompt)) return false
  return new RegExp(`\\b(?:${alt})\\b`, 'i').test(prompt)
}

// zsh reads `$VAR:t` as a history modifier; `${VAR}:t` is the same text in bash and zsh.
// Skips single-quoted text and everything after the first heredoc line.
export function fixZshColon(command: string): string {
  const hd = command.search(/<<-?\s*['"]?\w+/)
  const nl = hd < 0 ? -1 : command.indexOf('\n', hd)
  const limit = nl < 0 ? command.length : nl
  let out = ''
  let sq = false
  let dq = false
  for (let i = 0; i < limit; i++) {
    const ch = command[i]!
    if (ch === '\\' && !sq) {
      out += ch + (command[i + 1] ?? '')
      i++
      continue
    }
    if (ch === "'" && !dq) sq = !sq
    else if (ch === '"' && !sq) dq = !dq
    else if (ch === '$' && !sq) {
      const m = /^\$([A-Za-z_][A-Za-z0-9_]*):(?=[A-Za-z&])/.exec(command.slice(i, limit))
      if (m) {
        out += '${' + m[1] + '}:'
        i += m[0].length - 1
        continue
      }
    }
    out += ch
  }
  return out + command.slice(limit)
}

// The path a `git worktree add` creates; undefined for any other command.
export function worktreeAddPath(command: string): string | undefined {
  const m = /\bgit\s+(?:-[Cc]\s+\S+\s+)*worktree\s+add\b([^;&|\n]*)/.exec(command)
  if (!m) return undefined
  const words = m[1]!.trim().split(/\s+/).filter(Boolean)
  for (let i = 0; i < words.length; i++) {
    const w = words[i]!
    if (['-b', '-B', '--reason'].includes(w)) { i++; continue }
    if (w === '--') return words[i + 1]
    if (!w.startsWith('-')) return w
  }
  return undefined
}

// Worktrees live inside their repo (AGENTS.md "Worktrees"): <repo>/.worktrees/, <repo>/.claude/worktrees/, or Codex's ~/.codex/worktrees/.
export function worktreeAllowed(path: string, top: string, home: string): boolean {
  return [`${top}/.worktrees/`, `${top}/.claude/worktrees/`, `${home}/.codex/worktrees/`].some(p => path.startsWith(p))
}

type Call = { tool: string; action?: unknown; isolation?: unknown; skill?: unknown }

// Claude cloud outputs (AGENTS.md "No Claude cloud in personal"); reads stay allowed.
export function cloudOutput(e: Call): string | undefined {
  const action = typeof e.action === 'string' ? e.action : undefined
  if (e.tool === 'Artifact' && (action === undefined || ['publish', 'delete', 'pin', 'unpin'].includes(action)))
    return 'publishing an Artifact'
  if (e.tool === 'ArtifactData' && action !== undefined && ['set', 'update', 'delete', 'batch'].includes(action))
    return 'writing an Artifact database'
  if (/^mcp__claude_ai_Claude_Docs__(batch|create|update|delete)$/.test(e.tool)) return 'writing a Claude Doc'
  if (e.tool === 'RemoteTrigger') return 'starting a remote trigger'
  if (e.tool === 'Agent' && e.isolation === 'remote') return 'launching a remote agent'
  if (e.tool === 'Skill' && e.skill === 'schedule') return 'scheduling a cloud routine'
  return undefined
}

// Every personal repo commits as Denzil10's noreply address (owner, 2026-10-24); `~/.gitconfig-personal` sets it.
export const PERSONAL_EMAIL = 'Denzil10@users.noreply.github.com'

// ~/.home (setup included) and its ~/.agents alias.
export const isPersonalTree = (dir: string): boolean => /^\/Users\/[^/]+\/(\.home|\.agents)(\/|$)/.test(dir)

const VALUE = String.raw`(?:"([^"]*)"|'([^']*)'|([^\s;&|]+))`

// Commit emails a command would set: git config, `git -c`, GIT_*_EMAIL env, `--author`. `global` marks a ~/.gitconfig write.
export function identityWrites(command: string): { email: string; global: boolean }[] {
  const found: { email: string; global: boolean }[] = []
  const pick = (m: RegExpMatchArray, i: number) => m[i] ?? m[i + 1] ?? m[i + 2] ?? ''
  for (const m of command.matchAll(new RegExp(String.raw`\bgit\b([^;&|\n]*?)\bconfig\b([^;&|\n]*?)\buser\.email(?:\s+|=)${VALUE}`, 'g')))
    if (!/--(?:unset|get)/.test(m[2]!)) found.push({ email: pick(m, 3), global: /--global|--system/.test(m[2]!) })
  for (const m of command.matchAll(new RegExp(String.raw`\bgit\b[^;&|\n]*?\s-c\s+user\.email=${VALUE}`, 'g')))
    found.push({ email: pick(m, 1), global: false })
  for (const m of command.matchAll(new RegExp(String.raw`\bGIT_(?:AUTHOR|COMMITTER)_EMAIL=${VALUE}`, 'g')))
    found.push({ email: pick(m, 1), global: false })
  for (const m of command.matchAll(/--author[=\s]+(?:"[^"]*<([^>]*)>"|'[^']*<([^>]*)>')/g))
    found.push({ email: m[1] ?? m[2] ?? '', global: false })
  return found
}

export const offIdentity = (w: { email: string; global: boolean }): boolean =>
  w.global || w.email.toLowerCase() !== PERSONAL_EMAIL.toLowerCase()

// Shell writes to ~/.gitconfig-personal (redirect, tee, sed -i, git config --file).
export const writesPersonalGitconfig = (command: string): boolean =>
  /\.gitconfig-personal/.test(command) && /(>|\btee\b|\bsed\s+-i|--file|\s-f\s|\bmv\b|\bcp\b|\brm\b)/.test(command)
