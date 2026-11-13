import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';

const SOURCE = process.cwd();
const ZERO = '0'.repeat(40);
const TOKEN = ['ghp', createHash('sha256').update('push policy fixture').digest('hex').slice(0, 36)].join('_');
const fixtures: string[] = [];
afterAll(() => { for (const path of fixtures) rmSync(path, { recursive: true, force: true }); });

function bundlePaths(): string[] {
  const manifest: unknown = JSON.parse(readFileSync('config/agents/repository.json', 'utf8'));
  if (!manifest || typeof manifest !== 'object' || !('files' in manifest) ||
      !manifest.files || typeof manifest.files !== 'object') throw new Error('Invalid hook manifest');
  return [...Object.keys(manifest.files), 'config/agents/repository.json'].map(path => {
    if (isAbsolute(path) || path.split('/').includes('..')) throw new Error('Unsafe bundle path');
    return path;
  });
}
const BUNDLE = bundlePaths();
const BASE_ENV = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  !key.startsWith('GIT_') && !key.startsWith('PYTHON')));

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'jsolly-push-policy-'));
  fixtures.push(root);
  const repo = join(root, 'repo'); const home = join(root, 'home'); const bin = join(root, 'bin');
  for (const dir of [repo, home, bin, join(root, 'tmp')]) mkdirSync(dir);
  const env = {
    ...BASE_ENV, HOME: home, TMPDIR: join(root, 'tmp'),
    XDG_CACHE_HOME: join(home, 'cache'), XDG_CONFIG_HOME: join(home, 'config'),
    XDG_STATE_HOME: join(home, 'state'), XDG_DATA_HOME: join(home, 'data'),
    GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_AUTHOR_NAME: 'Fixture', GIT_AUTHOR_EMAIL: 'fixture@example.invalid',
    GIT_COMMITTER_NAME: 'Fixture', GIT_COMMITTER_EMAIL: 'fixture@example.invalid',
  };
  function git(...args: string[]) {
    const r = spawnSync('git', ['-c', 'core.hooksPath=/dev/null', ...args], { cwd: repo, env, encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`git ${args.join(' ')}: ${r.stderr}`);
    return r.stdout.trim();
  }
  for (const path of BUNDLE) {
    const target = join(repo, path); mkdirSync(dirname(target), { recursive: true });
    cpSync(join(SOURCE, path), target);
  }
  git('init', '-q', '-b', 'main');
  git('config', 'maintenance.auto', 'false');
  git('remote', 'add', 'origin', 'https://github.com/jsolly/jsolly.git');
  function commit(text: string) {
    writeFileSync(join(repo, 'safe.txt'), text); git('add', '-A'); git('commit', '-qm', 'fixture');
    return git('rev-parse', 'HEAD');
  }
  const base = commit('baseline\n'); git('update-ref', 'refs/remotes/origin/main', base);
  const install = spawnSync('bash', ['scripts/repo-python.sh', 'scripts/repo-hooks.py', 'install'], {
    cwd: repo, env, encoding: 'utf8',
  });
  if (install.status !== 0) throw new Error(install.stderr);
  const selected = spawnSync('git', ['config', '--type=path', '--get', 'core.hooksPath'], {
    cwd: repo, env, encoding: 'utf8',
  });
  if (selected.status !== 0) throw new Error(selected.stderr);
  const hook = join(selected.stdout.trim(), 'pre-push');
  if (!resolve(hook).startsWith(`${resolve(repo)}/.git/`)) throw new Error('Hook escaped fixture');
  const log = join(root, 'network-tools.log'); writeFileSync(log, '');
  for (const name of ['uv', 'uvx', 'semgrep', 'osv-scanner', 'curl', 'wget', 'npm']) {
    writeFileSync(join(bin, name), `#!/usr/bin/env bash\nprintf '%s\\n' '${name}' >> "$CALL_LOG"\nexit 97\n`, { mode: 0o755 });
  }
  function push(input: string) {
    const r = spawnSync('bash', [hook, 'origin'], {
      cwd: repo, encoding: 'utf8', input,
      env: { ...env, PATH: `${bin}:${process.env['PATH'] ?? '/usr/bin:/bin'}`, CALL_LOG: log },
    });
    expect(readFileSync(log, 'utf8')).toBe('');
    return { status: r.status, out: `${r.stdout}${r.stderr}` };
  }
  return { base, commit, git, push };
}
function ref(local: string, remote: string) { return `refs/heads/topic ${local} refs/heads/topic ${remote}\n`; }

describe('installed gitleaks-only pre-push', () => {
  it('accepts clean updated and new refs without network tools', () => {
    const f = fixture(); const tip = f.commit('clean update\n');
    for (const remote of [f.base, ZERO]) {
      const r = f.push(ref(tip, remote)); expect(r.status, r.out).toBe(0);
      expect(r.out).toContain('no leaks found');
    }
  });
  it('rejects a secret removed by a later outgoing commit', () => {
    const f = fixture(); f.commit(TOKEN); const tip = f.commit('removed\n');
    const r = f.push(ref(tip, f.base)); expect(r.status, r.out).not.toBe(0);
    expect(r.out).toContain('leaks found'); expect(r.out).not.toContain(TOKEN);
  });
  it('excludes only advertised remote history', () => {
    const f = fixture(); const old = f.commit(TOKEN); const tip = f.commit('removed\n');
    const r = f.push(ref(tip, old)); expect(r.status, r.out).toBe(0);
  });
  it('checks every supplied ref, including a non-HEAD tip', () => {
    const f = fixture(); const clean = f.commit('clean\n'); const leak = f.commit(TOKEN);
    f.git('switch', '-q', '--detach', clean);
    const r = f.push(ref(clean, f.base) + ref(leak, f.base));
    expect(r.status, r.out).not.toBe(0); expect(r.out).not.toContain(TOKEN);
  });
});
