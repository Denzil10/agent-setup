import { expect, test } from 'claude-code/testing'

const PERSONAL = '/Users/d/.home/self/dashboard'
const WORK = '/Users/d/Projects/acme-api'
const MINE = 'git@github.com:Denzil10/admin.git'
const ORG = 'git@github.com:AcmeCorp/api.git'

// Beneath the plugin: a fixed cwd/HOME, git remotes per repo, and a Bash that records what reached it.
function world(on: any, cwd: string, remotes: Record<string, string> = { origin: MINE }) {
  const ran: string[] = []
  on('session.cwd', () => ({ value: cwd }))
  on('env.get', () => ({ value: '/Users/d' }))
  on('clock.now', () => ({ value: 0 }))
  on('process.run', (_$: unknown, e: any) => {
    const args: string[] = e.argv.slice(3)
    const out = (stdout: string) => ({ value: { exitCode: stdout ? 0 : 1, stdout, stderr: '' } })
    if (args[1] === '--show-toplevel') return out(e.argv[2])
    if (args[0] === 'rev-parse') return out(remotes.origin ? 'origin/main' : '')
    if (args[0] === 'remote' && args[1] === '-v') return out(Object.entries(remotes).map(([n, u]) => `${n}\t${u} (push)`).join('\n'))
    if (args[0] === 'remote') return out(remotes[args[3]!] ?? '')
    return out('')
  })
  on('prompt.submit', (_$: unknown, e: any) => ({ text: e.text }))
  on('session.start', (_$: unknown, e: any) => ({ cwd: e.cwd }))
  on('tool.call', (_$: unknown, e: any) => {
    ran.push(e.command ?? e.tool)
    return { result: 'ok' }
  })
  return ran
}

const say = ($: any, text: string) => $.prompt.submit({ text, origin: { kind: 'composer' }, wait: false })

test('personal repo pushes freely', async ($, on) => {
  const ran = world(on, PERSONAL)
  await $.tool.call({ tool: 'Bash', command: 'git push' })
  await $.tool.call({ tool: 'Bash', command: 'gh pr create --fill' })
  expect(ran).toEqual(['git push', 'gh pr create --fill'])
})

test('work repos push freely from their own sessions', async ($, on) => {
  const ran = world(on, WORK, { origin: ORG })
  await $.tool.call({ tool: 'Bash', command: 'git push' })
  expect(ran).toEqual(['git push'])
})

test('from personal, a push into a work dir is blocked', async ($, on) => {
  const ran = world(on, PERSONAL)
  const denied: any = await $.tool.call({ tool: 'Bash', command: 'git -C ~/Projects/acme-api push' })
  await $.tool.call({ tool: 'Bash', command: 'cd ../../../Projects/acme-api && git push origin main' })
  expect(ran).toEqual([])
  expect(JSON.stringify(denied)).toContain('Github Boundary')
})

test('from personal, a push to a work remote is blocked', async ($, on) => {
  const ran = world(on, PERSONAL, { origin: MINE, work: ORG })
  await $.tool.call({ tool: 'Bash', command: 'git push work main' })
  await $.tool.call({ tool: 'Bash', command: `git push ${ORG} HEAD` })
  await $.tool.call({ tool: 'Bash', command: 'gh pr create -R AcmeCorp/api --fill' })
  await $.tool.call({ tool: 'Bash', command: 'gh api repos/AcmeCorp/api/issues -X POST -f title=t' })
  await $.tool.call({ tool: 'Bash', command: 'git push origin main' })
  expect(ran).toEqual(['git push origin main'])
})

test('from personal, a repo whose default push remote is work is blocked', async ($, on) => {
  const ran = world(on, PERSONAL, { origin: ORG })
  await $.tool.call({ tool: 'Bash', command: 'git push' })
  await $.tool.call({ tool: 'Bash', command: 'gh pr merge 3' })
  expect(ran).toEqual([])
})

test('headless personal runs are held to the same boundary', async ($, on) => {
  const ran = world(on, PERSONAL, { origin: ORG })
  await $.session.start({ cwd: PERSONAL, surface: null, isInteractive: false })
  await $.tool.call({ tool: 'Bash', command: 'git push' })
  expect(ran).toEqual([])
})

test('cloud CLI in personal needs approval naming it', async ($, on) => {
  const ran = world(on, PERSONAL)
  await say($, 'deploy it')
  await $.tool.call({ tool: 'Bash', command: 'gcloud run deploy' })
  expect(ran).toEqual([])
  await say($, 'ok use gcloud')
  await $.tool.call({ tool: 'Bash', command: 'gcloud run deploy' })
  expect(ran).toEqual(['gcloud run deploy'])
})

test('Artifact publish blocked in personal', async ($, on) => {
  const ran = world(on, PERSONAL)
  await $.tool.call({ tool: 'Artifact', file_path: 'a.html' })
  expect(ran).toEqual([])
})

test('Artifact publish allowed at work', async ($, on) => {
  const ran = world(on, WORK)
  await $.tool.call({ tool: 'Artifact', file_path: 'a.html' })
  expect(ran).toEqual(['Artifact'])
})

test('zsh colon rewritten before Bash runs', async ($, on) => {
  const ran = world(on, PERSONAL)
  await $.tool.call({ tool: 'Bash', command: 'docker tag a "$IMG:latest"' })
  expect(ran).toEqual(['docker tag a "${IMG}:latest"'])
})

test('headless runs skip the cloud-CLI ask but keep the rewrite', async ($, on) => {
  const ran = world(on, PERSONAL)
  await $.session.start({ cwd: PERSONAL, surface: null, isInteractive: false })
  await $.tool.call({ tool: 'Bash', command: 'aws s3 ls' })
  await $.tool.call({ tool: 'Bash', command: 'echo $A:b' })
  expect(ran).toEqual(['aws s3 ls', 'echo ${A}:b'])
})

test('worktrees outside their repo are blocked', async ($, on) => {
  const ran = world(on, WORK, { origin: ORG })
  const denied: any = await $.tool.call({ tool: 'Bash', command: 'git worktree add ../acme-wt-x -b x' })
  await $.tool.call({ tool: 'Bash', command: 'git worktree add .worktrees/x -b x' })
  expect(denied.deny).toContain('outside its repo')
  expect(ran).toEqual(['git worktree add .worktrees/x -b x'])
})

test('personal commit identity stays Denzil10 noreply', async ($, on) => {
  const ran = world(on, PERSONAL)
  const denied: any = await $.tool.call({ tool: 'Bash', command: 'git config user.email me@example.com' })
  await $.tool.call({ tool: 'Bash', command: 'GIT_AUTHOR_EMAIL=x@y.z git commit -m a' })
  await $.tool.call({ tool: 'Write', file_path: '/Users/d/.gitconfig-personal', content: '' })
  await $.tool.call({ tool: 'Bash', command: 'git config user.email Denzil10@users.noreply.github.com' })
  expect(ran).toEqual(['git config user.email Denzil10@users.noreply.github.com'])
  expect(JSON.stringify(denied)).toContain('Git identity')
})

test('the user can ask to change the git identity', async ($, on) => {
  const ran = world(on, PERSONAL)
  await say($, 'change the git identity for this repo')
  await $.tool.call({ tool: 'Bash', command: 'git config user.email a@b.c' })
  expect(ran).toEqual(['git config user.email a@b.c'])
})

test('work repos set their own identity', async ($, on) => {
  const ran = world(on, WORK, { origin: ORG })
  await $.tool.call({ tool: 'Bash', command: 'git config user.email me@acme.example' })
  expect(ran).toEqual(['git config user.email me@acme.example'])
})
