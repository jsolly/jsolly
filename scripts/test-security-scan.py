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


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'config', 'core.hooksPath', '/dev/null')
    (root / 'safe.txt').write_text('safe baseline\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'baseline')
    return root


def secret():
    # Synthetic provider-shaped credential assembled at runtime, never a live token.
    return 'ghp_' + hashlib.sha256(b'outgoing hook regression').hexdigest()[:36]


def commit_secret(root):
    (root / 'credential.txt').write_text('token = "' + secret() + '"\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'bypassed commit')
    return git(root, 'rev-parse', 'HEAD')


def prepush(root, tmp_path, lines):
    snapshot = tmp_path / 'snapshot'
    (snapshot / 'hooks').mkdir(parents=True, exist_ok=True)
    (snapshot / 'gate').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'gate/hooks/pre-commit', snapshot / 'hooks/pre-push')
    shutil.copy2(ROOT / 'gate/gate-lib.sh', snapshot / 'gate/gate-lib.sh')
    return subprocess.run(['bash', str(snapshot / 'hooks/pre-push'), 'origin'],
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


@pytest.mark.parametrize('line', ['malformed\n', 'ref bad ref bad\n'])
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
    git(repo, 'remote', 'add', 'origin', 'https://github.com/example/fixture.git')
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
