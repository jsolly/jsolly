"""Exercise outgoing Git objects and Cursor snapshots, including bypassed commits."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('security_scan', ROOT / 'gate/security-scan.py')
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


@pytest.fixture(autouse=True)
def isolated_git_environment(monkeypatch):
    # Git's hook environment can select the *real committing index*. Clear it
    # for the entire fixture, including imported scanner calls and CLI children.
    for key in list(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    for key, value in {
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
        'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
    }.items():
        monkeypatch.setenv(key, value)


def git(root, *args):
    root = root.resolve()
    if args[0] != 'init':
        common = Path(subprocess.check_output(
            ['git', '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
            text=True).strip()).resolve()
        assert common.is_relative_to(root), 'Fixture escaped its Git directory'
    # These are isolated fixture commits, including deliberate hook bypasses.
    # The installed native pre-push path is invoked separately below.
    return subprocess.check_output(
        ['git', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    manifest = json.loads((ROOT / 'config/agents/repository.json').read_text())
    for name in [*manifest['files'], 'config/agents/repository.json']:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'remote', 'add', 'origin', 'https://github.com/' + manifest['repo'] + '.git')
    (root / 'safe.txt').write_text('safe baseline\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'baseline')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    tool(root, 'install')
    return root


def tool(root, *args):
    return subprocess.check_output(
        [sys.executable, '-I', str(root / 'scripts/repo-hooks.py'), *args, '--root', str(root)],
        cwd=root, text=True).strip()


def secret():
    # Synthetic provider-shaped credential assembled at runtime, never a live token.
    return 'ghp_' + hashlib.sha256(b'outgoing hook regression').hexdigest()[:36]


def commit_secret(root):
    (root / 'credential.txt').write_text('token = "' + secret() + '"\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'bypassed commit')
    return git(root, 'rev-parse', 'HEAD')


def prepush(root, tmp_path, lines):
    # Invoke the real installed entry, not a copied shell hook without its trust chain.
    hooks = Path(subprocess.check_output(
        ['git', '-C', str(root), 'config', '--type=path', '--get', 'core.hooksPath'],
        text=True).strip())
    return subprocess.run(['bash', str(hooks / 'pre-push'), 'origin'],
                          cwd=root, input=lines, text=True, capture_output=True)


def test_actual_pre_push_refuses_secret_committed_with_hooks_bypassed(repo, tmp_path):
    baseline = git(repo, 'rev-parse', 'HEAD')
    head = commit_secret(repo)
    result = prepush(repo, tmp_path, f'refs/heads/main {head} refs/heads/main {baseline}\n')
    assert result.returncode != 0, result.stdout + result.stderr
    assert secret() not in result.stdout + result.stderr
    assert 'leaks found' in result.stderr


def test_pre_push_checks_every_ref_and_ignores_deletions(repo, tmp_path):
    baseline = git(repo, 'rev-parse', 'HEAD')
    head = commit_secret(repo)
    zero = '0' * 40
    lines = (f'(delete) {zero} refs/heads/deleted {baseline}\n'
             f'refs/heads/safe {baseline} refs/heads/safe {baseline}\n'
             f'refs/heads/new {head} refs/heads/new {zero}\n')
    result = prepush(repo, tmp_path, lines)
    assert result.returncode != 0
    assert 'leaks found' in result.stderr


def test_pre_push_limits_scan_to_outgoing_history(repo, tmp_path):
    held = commit_secret(repo)
    (repo / 'safe.txt').write_text('new safe change\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'safe outgoing change')
    head = git(repo, 'rev-parse', 'HEAD')
    result = prepush(repo, tmp_path, f'refs/heads/main {head} refs/heads/main {held}\n')
    assert result.returncode == 0, result.stderr
    assert 'semgrep' in result.stderr
    assert secret() not in result.stdout + result.stderr


def test_pre_push_skips_network_scanners_for_an_unchanged_tip(repo, tmp_path):
    head = git(repo, 'rev-parse', 'HEAD')
    result = prepush(repo, tmp_path, f'refs/heads/main {head} refs/heads/main {head}\n')
    assert result.returncode == 0, result.stderr
    assert 'semgrep' not in result.stderr
    assert 'osv-scanner' not in result.stderr


@pytest.mark.parametrize('line', ['malformed\n', 'ref bad ref bad\n', 'malformed'])
def test_pre_push_refuses_malformed_input(repo, tmp_path, line):
    result = prepush(repo, tmp_path, line)
    assert result.returncode != 0
    assert 'Malformed pre-push input' in result.stderr


def test_cursor_scans_staged_and_working_files_independently(repo, tmp_path, monkeypatch):
    (repo / 'safe.txt').write_text('staged-secret')
    git(repo, 'add', '.')
    (repo / 'safe.txt').write_text('safe working copy')
    (repo / 'untracked.txt').write_text('untracked-secret')
    captures = []

    def capture(tree, *args):
        captures.append({p.name: p.read_text() for p in tree.rglob('*') if p.is_file()})

    monkeypatch.setattr(scan, 'secrets', capture)
    scan.cursor(repo, {'command': 'git commit'})
    assert captures[0]['safe.txt'] == 'safe working copy'
    assert captures[0]['untracked.txt'] == 'untracked-secret'
    assert captures[1]['safe.txt'] == 'staged-secret'


def test_cursor_refuses_symlink_escape(repo, tmp_path):
    (repo / 'link').symlink_to(tmp_path)
    with pytest.raises(ValueError, match='Unsafe path'):
        scan.working_tree(repo, tmp_path / 'scan')


def test_cursor_cli_returns_deny_on_real_secret_and_malformed_input(repo):
    commit_secret(repo)
    for payload in [json.dumps({'command': 'git push'}), '{broken']:
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'gate/security-scan.py'),
                                 'cursor', '--root', str(repo)], input=payload,
                                text=True, capture_output=True)
        assert result.returncode != 0
        assert json.loads(result.stdout)['permission'] == 'deny'
        assert secret() not in result.stdout + result.stderr


def test_dependency_scanner_cannot_use_repository_ignore_config(repo, monkeypatch):
    calls = []

    def capture(args, root):
        calls.append(args)
        assert Path(args[args.index('--config') + 1]).read_text() == ''
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(scan, 'run', capture)
    with pytest.raises(subprocess.CalledProcessError):
        scan.dependencies('osv-scanner', repo)
    assert '--all-vulns' in calls[0]


def test_source_scanner_findings_block_ci(repo, monkeypatch):
    calls = []

    def failing(name, args, root):
        calls.append((name, args))
        raise subprocess.CalledProcessError(1, name)

    monkeypatch.setattr(scan, 'python_tool', failing)
    with pytest.raises(subprocess.CalledProcessError):
        scan.source(repo)
    assert calls[0][0] == 'semgrep'
    assert '--error' in calls[0][1]
    assert 'p/default' in calls[0][1]
    assert '--x-ignore-semgrepignore-files' in calls[0][1]


def test_stale_tracking_ref_cannot_exclude_a_new_branch_secret(repo, tmp_path):
    head = commit_secret(repo)
    git(repo, 'update-ref', 'refs/remotes/origin/deleted', head)
    result = prepush(repo, tmp_path,
                     f'refs/heads/new {head} refs/heads/new {"0" * 40}\n')
    assert result.returncode != 0
    assert 'leaks found' in result.stderr


def test_branch_gitleaks_policies_cannot_suppress_push_or_cursor(repo, tmp_path):
    baseline = git(repo, 'rev-parse', 'HEAD')
    head = commit_secret(repo)
    (repo / '.gitleaks.toml').write_text('[extend]\nuseDefault = true\n[allowlist]\npaths = [".*"]\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'attempted scan policy bypass')
    head = git(repo, 'rev-parse', 'HEAD')
    pushed = prepush(repo, tmp_path, f'refs/heads/main {head} refs/heads/main {baseline}\n')
    assert pushed.returncode != 0
    assert 'leaks found' in pushed.stderr
    cursor = subprocess.run([sys.executable, '-I', str(ROOT / 'gate/security-scan.py'),
                             'cursor', '--root', str(repo)],
                            input=json.dumps({'command': 'git push'}), text=True, capture_output=True)
    assert cursor.returncode != 0
    assert json.loads(cursor.stdout)['permission'] == 'deny'
    (repo / '.gitleaksignore').write_text(f'{head}:credential.txt:github-pat:1\n')
    ignored = prepush(repo, tmp_path, f'refs/heads/main {head} refs/heads/main {baseline}\n')
    assert ignored.returncode != 0
    assert '.gitleaksignore is unsupported' in ignored.stderr


def test_push_scans_the_commit_tree_not_the_worktree(repo, monkeypatch):
    (repo / 'safe.txt').write_text('committed\n')
    (repo / 'package.json').write_text('{"name":"fixture"}\n')
    (repo / 'package-lock.json').write_text('{"lock":"committed"}\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'committed tree')
    sha = git(repo, 'rev-parse', 'HEAD')
    (repo / 'safe.txt').write_text('dirty worktree\n')
    (repo / 'package-lock.json').write_text('{"lock":"dirty"}\n')
    seen = {}
    monkeypatch.setattr(scan, 'source', lambda root: seen.setdefault('source', (root / 'safe.txt').read_text()))
    monkeypatch.setattr(scan, 'dependency_scan', lambda root: seen.setdefault('deps', (root / 'package-lock.json').read_text()))
    scan.push_commit(repo, sha)
    assert seen == {'source': 'committed\n', 'deps': '{"lock":"committed"}\n'}


def test_push_requires_a_lockfile_and_does_not_follow_symlinks(repo, tmp_path, monkeypatch):
    outside = tmp_path / 'outside.txt'
    outside.write_text('outside-value')
    (repo / 'package.json').symlink_to(outside)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'linked manifest')
    sha = git(repo, 'rev-parse', 'HEAD')
    seen = {}

    def capture(root):
        manifest = root / 'package.json'
        assert not manifest.is_symlink()
        seen['text'] = manifest.read_text()

    def refuse_dependencies(root):
        raise AssertionError('scanned a dependency manifest')

    monkeypatch.setattr(scan, 'source', capture)
    monkeypatch.setattr(scan, 'dependency_scan', refuse_dependencies)
    with pytest.raises(ValueError, match='package-lock.json'):
        scan.push_commit(repo, sha)
    assert 'outside-value' not in seen['text']


def test_push_cli_requires_a_commit(repo, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['security-scan.py', 'push', '--root', str(repo)])
    assert scan.main() == 1


def test_ci_attempts_dependency_scan_after_source_failure(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, 'argv', ['security-scan.py', 'ci', '--root', str(repo)])
    monkeypatch.setattr(scan, 'structural', lambda root: calls.append('workflow'))

    def failed_source(root):
        calls.append('source')
        raise subprocess.CalledProcessError(1, 'semgrep')

    monkeypatch.setattr(scan, 'source', failed_source)
    monkeypatch.setattr(scan, 'dependency_scan', lambda root: calls.append('dependencies'))
    assert scan.main() == 1
    assert calls == ['workflow', 'source', 'dependencies']


def test_installed_push_refuses_corrupt_library_before_execution(repo, tmp_path):
    hooks = Path(git(repo, 'config', '--local', '--get', 'core.hooksPath'))
    marker = tmp_path / 'unverified-library-executed'
    library = hooks.parent / 'gate/gate-lib.sh'
    library.write_text('touch "' + str(marker) + '"\n' + library.read_text())
    result = prepush(repo, tmp_path, '')
    assert result.returncode != 0
    assert not marker.exists()
    assert 'corrupt' in result.stderr


def test_installed_push_refuses_foreign_origin_even_for_deletions(repo, tmp_path):
    head = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'remote', 'set-url', 'origin', 'https://github.com/foreign/fixture.git')
    result = prepush(repo, tmp_path, f'(delete) {"0" * 40} refs/heads/main {head}\n')
    assert result.returncode != 0
    assert 'identity' in result.stderr


def test_installed_push_refuses_revoked_bundle_authorization(repo, tmp_path):
    hook = repo / '.git-hooks/pre-commit'
    hook.write_text(hook.read_text() + '\n# reviewed fixture update\n')
    digest = tool(repo, 'digest')
    tool(repo, 'approve', '--digest', digest)
    tool(repo, 'install')
    git(repo, 'config', '--local', '--unset-all', 'repo.trustedGateBundle')
    result = prepush(repo, tmp_path, '')
    assert result.returncode != 0
    assert 'not trusted' in result.stderr


def test_fixture_execution_cannot_mutate_an_inherited_outer_index(repo, tmp_path):
    outer_index = repo / '.git/index'
    before = outer_index.read_bytes()
    poisoned = dict(os.environ, GIT_INDEX_FILE=str(outer_index), GIT_DIR=str(repo / '.git'),
                    GIT_WORK_TREE=str(repo))
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
         '--basetemp', str(tmp_path / 'child-fixtures'),
         str(Path(__file__).resolve()) + '::test_actual_pre_push_refuses_secret_committed_with_hooks_bypassed',
         str(Path(__file__).resolve()) + '::test_cursor_scans_staged_and_working_files_independently'],
        cwd=repo, env=poisoned, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outer_index.read_bytes() == before


def test_native_push_rejects_stale_worktree_snapshot_before_sourcing(repo, tmp_path):
    old_hooks = Path(git(repo, 'config', '--local', '--get', 'core.hooksPath'))
    hook = repo / '.git-hooks/pre-commit'
    hook.write_text(hook.read_text() + '\n# independently reviewed second bundle\n')
    digest = tool(repo, 'digest')
    tool(repo, 'approve', '--digest', digest)
    tool(repo, 'install')
    new_hooks = Path(git(repo, 'config', '--local', '--get', 'core.hooksPath'))
    assert old_hooks != new_hooks
    git(repo, 'config', 'extensions.worktreeConfig', 'true')
    git(repo, 'config', '--worktree', 'core.hooksPath', str(old_hooks))
    marker = tmp_path / 'stale-library-executed'
    library = old_hooks.parent / 'gate/gate-lib.sh'
    library.write_text('touch "' + str(marker) + '"\n' + library.read_text())
    # Let Git choose the effective entry, including its config.worktree override.
    result = subprocess.run(['git', '-C', str(repo), 'hook', 'run', 'pre-push', '--', 'origin'],
                            input='', text=True, capture_output=True)
    assert result.returncode != 0
    assert not marker.exists()
    assert 'snapshot or worktree hooksPath is stale' in result.stderr
