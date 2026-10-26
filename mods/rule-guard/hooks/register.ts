import type { EngineInterface, Register } from 'claude-code'
import { worktreeAddPath, worktreeAllowed, resolve, cloudCli, cloudOutput, fixZshColon, identityWrites, isPersonalTree, offIdentity, PERSONAL_EMAIL, writesPersonalGitconfig, isRemote, isWorkOwner, namedOwners, ownerOf, pushRemote, requested, targetDir, zoneOf } from './rules.ts'

// GitHub owners of work repos: the org and the work account.
const WORK_OWNERS = ['AcmeCorp', 'acme-dev']
const USER_ORIGINS = ['composer', 'bridge', 'sdk']

// The user's latest prompt: what "explicit approval" is judged against.
// Headless runs (claude -p automations) have no one to ask, so the cloud-CLI rule skips them.
let lastPrompt = ''
let interactive = true

export const register: Register = on => {
  on('session.start', ($, e, next) => {
    interactive = e.isInteractive
    return next(e)
  })

  on('prompt.submit', ($, e, next) => {
    if (USER_ORIGINS.includes(e.origin.kind)) lastPrompt = e.text
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    const cwd = await $.session.cwd()

    const cloud = zoneOf(cwd) === 'personal' ? cloudOutput(e as { tool: string }) : undefined
    if (cloud) return { deny: `${$.plugin.name}: ${cloud} is blocked in personal (~/.home) (AGENTS.md "No Claude cloud in personal"). Write a local file such as local/reports/*.html instead.` }

    const home = (await $.env.get('HOME')) ?? ''
    const identity = `(Git identity, owner 2026-10-24: personal repos commit as ${PERSONAL_EMAIL} via ~/.gitconfig-personal, no per-repo overrides; ~/.agents/docs/claude-code.md)`
    const askedIdentity = requested(lastPrompt, ['gitconfig-personal', 'git identity', 'commit email'])
    if ((e.tool === 'Edit' || e.tool === 'Write') && !askedIdentity) {
      const path = resolve(String((e as { file_path?: unknown }).file_path ?? ''), cwd, home)
      if (path === `${home}/.gitconfig-personal`) return { deny: `${$.plugin.name}: ~/.gitconfig-personal changes only on the user's word ${identity}.` }
    }

    if (e.tool !== 'Bash') return next(e)

    const dir = targetDir(e.command, cwd, home)
    const zone = zoneOf(dir)

    if ((isPersonalTree(cwd) || isPersonalTree(dir)) && !askedIdentity) {
      const off = identityWrites(e.command).find(offIdentity)
      if (off || writesPersonalGitconfig(e.command))
        return { deny: `${$.plugin.name}: ${off ? `setting commit email ${off.email || '(empty)'}${off.global ? ' globally' : ''}` : 'writing ~/.gitconfig-personal'} is blocked ${identity}.` }
    }

    if (zoneOf(cwd) === 'personal' && isRemote(e.command)) {
      const target = await workTarget($, e.command, dir)
      if (target)
        return { deny: `${$.plugin.name}: work in personal (~/.home) never pushes to a work repo (${target}) (AGENTS.md "Github Boundary").` }
    }

    const wt = worktreeAddPath(e.command)
    if (wt) {
      const top = (await git($, dir, ['rev-parse', '--show-toplevel'])) || dir
      const path = resolve(wt, dir, home)
      if (!worktreeAllowed(path, top, home))
        return { deny: `${$.plugin.name}: worktree at ${path} is outside its repo (AGENTS.md "Worktrees"). Use ${top}/.worktrees/<branch>.` }
    }

    const cli = interactive && zone === 'personal' ? cloudCli(e.command) : undefined
    if (cli && !requested(lastPrompt, [cli, 'cloud', 'approved', 'approve']))
      return { deny: `${$.plugin.name}: \`${cli}\` in personal (~/.home) needs explicit approval (AGENTS.md "Cloud Boundary"). Ask the user; naming ${cli} in their reply approves it.` }

    const command = fixZshColon(e.command)
    if (command !== e.command) $.ui.log(`${$.plugin.name}: rewrote $VAR: to \${VAR}:`, { to: 'debug' })
    return next({ ...e, command })
  })
}

// Why this remote action lands on a work repo, or undefined when it does not.
async function workTarget($: EngineInterface, command: string, dir: string): Promise<string | undefined> {
  if (zoneOf(dir) === 'work') return dir
  const named = namedOwners(command).find(o => isWorkOwner(o, WORK_OWNERS))
  if (named) return named
  if (/\bgit\b[^;&|\n]*\bpush\b/.test(command)) {
    const remote = pushRemote(command) ?? (await defaultPushRemote($, dir))
    const url = ownerOf(remote) ? remote : await git($, dir, ['remote', 'get-url', '--push', remote])
    return isWorkOwner(ownerOf(url), WORK_OWNERS) ? url : undefined
  }
  // gh picks its base repo from the remotes, so any work remote counts.
  const urls = (await git($, dir, ['remote', '-v'])).split('\n').map(l => l.split(/\s+/)[1] ?? '')
  return urls.find(u => isWorkOwner(ownerOf(u), WORK_OWNERS))
}

async function defaultPushRemote($: EngineInterface, dir: string): Promise<string> {
  const push = await git($, dir, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{push}'])
  return push.split('/')[0] || 'origin'
}

async function git($: EngineInterface, dir: string, args: readonly string[]): Promise<string> {
  const r = await $.process.run(['git', '-C', dir, ...args], { timeoutMs: 10_000 }).catch(() => undefined)
  return r?.exitCode === 0 ? r.stdout.trim() : ''
}
