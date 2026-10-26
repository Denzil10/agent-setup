import { expect, test } from 'claude-code/testing'
import { worktreeAddPath, worktreeAllowed, resolve, cloudCli, cloudOutput, fixZshColon, identityWrites, isPersonalTree, offIdentity, PERSONAL_EMAIL, writesPersonalGitconfig, isRemote, isWorkOwner, namedOwners, ownerOf, pushRemote, requested, targetDir, zoneOf } from '../hooks/rules.ts'

const HOME = '/Users/d'

test('zones', async () => {
  expect(zoneOf('/Users/d/.home/self/dashboard')).toBe('personal')
  expect(zoneOf('/Users/d/Projects/personal/admin')).toBe('work')
  expect(zoneOf('/Users/d/Projects/acme-api/src')).toBe('work')
  expect(zoneOf('/Users/d/tmp')).toBe('other')
  expect(zoneOf('/Users/d/.home/self/context')).toBe('personal')
  expect(zoneOf('/Users/d/.home/public/venture')).toBe('personal')
  expect(zoneOf('/Users/d/.home/setup/mods')).toBe('other')
  expect(zoneOf('/Users/d/.agents')).toBe('other')
  expect(zoneOf('/Users/d/.homely')).toBe('other')
})

test('target dir follows git -C and a leading cd', async () => {
  const cwd = '/Users/d/.home/self/dashboard'
  expect(targetDir('git push', cwd, HOME)).toBe(cwd)
  expect(targetDir('git -C ../../../Projects/acme-api push', cwd, HOME)).toBe('/Users/d/Projects/acme-api')
  expect(targetDir('cd ~/Projects/acme-api && git push', cwd, HOME)).toBe('/Users/d/Projects/acme-api')
})

test('remote git actions', async () => {
  for (const c of ['git push', 'git push -u origin main', 'git -C x push', 'gh pr create --fill', 'gh repo create x --public', 'gh api repos/a/b/issues -X POST -f title=t'])
    expect(isRemote(c)).toBe(true)
  for (const c of ['git status', 'git log --oneline', 'gh pr view 3', 'gh api repos/a/b', 'echo push'])
    expect(isRemote(c)).toBe(false)
})

test('owners and push remotes', async () => {
  expect(ownerOf('git@github.com:AcmeCorp/api.git')).toBe('AcmeCorp')
  expect(ownerOf('https://github.com/Denzil10/admin')).toBe('Denzil10')
  expect(ownerOf('origin')).toBeUndefined()
  expect(namedOwners('gh pr create -R AcmeCorp/api --fill')).toEqual(['AcmeCorp'])
  expect(namedOwners('gh api repos/AcmeCorp/x/pulls -X POST')).toEqual(['AcmeCorp'])
  expect(namedOwners('gh repo create acme-dev/tool --private')).toEqual(['acme-dev'])
  expect(pushRemote('git push')).toBeUndefined()
  expect(pushRemote('git push -u origin main')).toBe('origin')
  expect(pushRemote('git -C x push --force-with-lease work HEAD')).toBe('work')
  expect(pushRemote('git push -o ci.skip upstream')).toBe('upstream')
  expect(isWorkOwner('acmecorp', ['AcmeCorp'])).toBe(true)
  expect(isWorkOwner('Denzil10', ['AcmeCorp'])).toBe(false)
})

test('cloud CLIs only in command position', async () => {
  expect(cloudCli('aws s3 ls')).toBe('aws')
  expect(cloudCli('cd x && gcloud run deploy')).toBe('gcloud')
  expect(cloudCli('npx --yes vercel deploy')).toBe('vercel')
  expect(cloudCli('AWS_PROFILE=p aws sts get-caller-identity')).toBe('aws')
  expect(cloudCli('grep aws config.yml')).toBeUndefined()
  expect(cloudCli('ls ~/.aws')).toBeUndefined()
  expect(cloudCli('echo "use firebase later"')).toBeUndefined()
})

test('approval detection honours negation', async () => {
  expect(requested('ok use gcloud', ['gcloud'])).toBe(true)
  expect(requested("don't use gcloud", ['gcloud'])).toBe(false)
  expect(requested('fix the awsome bug', ['aws'])).toBe(false)
})

test('zsh colon rewrite', async () => {
  expect(fixZshColon('docker tag img "$IMAGE:latest"')).toBe('docker tag img "${IMAGE}:latest"')
  expect(fixZshColon('echo $HOST:port')).toBe('echo ${HOST}:port')
  expect(fixZshColon("echo '$KEEP:me'")).toBe("echo '$KEEP:me'")
  expect(fixZshColon('echo ${OK}:x $PATH:/bin')).toBe('echo ${OK}:x $PATH:/bin')
  expect(fixZshColon('cat <<EOF\n$X:y\nEOF')).toBe('cat <<EOF\n$X:y\nEOF')
  expect(fixZshColon('echo \\$NOT:me')).toBe('echo \\$NOT:me')
})

test('Claude cloud outputs', async () => {
  expect(cloudOutput({ tool: 'Artifact' })).toBe('publishing an Artifact')
  expect(cloudOutput({ tool: 'Artifact', action: 'read' })).toBeUndefined()
  expect(cloudOutput({ tool: 'mcp__claude_ai_Claude_Docs__batch' })).toBe('writing a Claude Doc')
  expect(cloudOutput({ tool: 'mcp__claude_ai_Claude_Docs__read' })).toBeUndefined()
  expect(cloudOutput({ tool: 'Agent', isolation: 'remote' })).toBe('launching a remote agent')
  expect(cloudOutput({ tool: 'Agent', isolation: 'worktree' })).toBeUndefined()
  expect(cloudOutput({ tool: 'Skill', skill: 'schedule' })).toBe('scheduling a cloud routine')
})

test('worktrees stay inside their repo', async () => {
  expect(worktreeAddPath('git worktree add ../repo-feat feat')).toBe('../repo-feat')
  expect(worktreeAddPath('git -C x worktree add -b fix/a .worktrees/fix-a main')).toBe('.worktrees/fix-a')
  expect(worktreeAddPath('git worktree add --detach --reason "x" -f /tmp/w')).toBe('/tmp/w')
  expect(worktreeAddPath('git worktree list')).toBeUndefined()
  const top = '/Users/d/Projects/api'
  expect(worktreeAllowed(resolve('.worktrees/fix-a', top, HOME), top, HOME)).toBe(true)
  expect(worktreeAllowed(resolve('.claude/worktrees/x', top, HOME), top, HOME)).toBe(true)
  expect(worktreeAllowed(resolve('~/.codex/worktrees/a/api', top, HOME), top, HOME)).toBe(true)
  expect(worktreeAllowed(resolve('../api-feat', top, HOME), top, HOME)).toBe(false)
  expect(worktreeAllowed(resolve('.worktrees', top, HOME), top, HOME)).toBe(false)
})

test('commit identity writes', async () => {
  const emails = (c: string) => identityWrites(c).filter(offIdentity).map(w => w.email)
  expect(emails('git config user.email me@example.com')).toEqual(['me@example.com'])
  expect(emails('git -C x config --local user.email "a@b.c"')).toEqual(['a@b.c'])
  expect(emails('git -c user.email=a@b.c commit -m x')).toEqual(['a@b.c'])
  expect(emails('GIT_AUTHOR_EMAIL=a@b.c git commit -m x')).toEqual(['a@b.c'])
  expect(emails('git commit --author="D <a@b.c>" -m x')).toEqual(['a@b.c'])
  expect(emails(`git config --global user.email ${PERSONAL_EMAIL}`)).toEqual([PERSONAL_EMAIL])
  expect(emails(`git config user.email ${PERSONAL_EMAIL}`)).toEqual([])
  expect(emails('git config user.email')).toEqual([])
  expect(emails('git config --unset user.email')).toEqual([])
  expect(emails('git config --get user.email && git log')).toEqual([])
  expect(emails('git log --format=%ae')).toEqual([])
  expect(writesPersonalGitconfig('cat ~/.gitconfig-personal')).toBe(false)
  expect(writesPersonalGitconfig('echo x >> ~/.gitconfig-personal')).toBe(true)
  expect(writesPersonalGitconfig('git config --file ~/.gitconfig-personal user.name x')).toBe(true)
  expect(isPersonalTree('/Users/d/.home/setup')).toBe(true)
  expect(isPersonalTree('/Users/d/.agents/mods')).toBe(true)
  expect(isPersonalTree('/Users/d/Projects/api')).toBe(false)
})
