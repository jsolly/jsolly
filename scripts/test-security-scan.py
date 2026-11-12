"""Exercise outgoing Git objects and Cursor snapshots, including bypassed commits."""
import errno
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tomllib
import urllib.error

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
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        # CI reaches semgrep.dev, so the tip scan must actually run there.
        assert 'semgrep==' + scan.VERSIONS['semgrep'] in result.stderr
    else:
        assert ('semgrep==' + scan.VERSIONS['semgrep'] in result.stderr
                or 'semgrep (tip) skipped: https://semgrep.dev/ is unreachable' in result.stderr)
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
    monkeypatch.setattr(scan, 'unreachable', lambda url, name: False)
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

    monkeypatch.setattr(scan, 'unreachable', lambda url, name: False)
    monkeypatch.setattr(scan, 'source', capture)
    monkeypatch.setattr(scan, 'dependency_scan', refuse_dependencies)
    with pytest.raises(ValueError, match='package-lock.json'):
        scan.push_commit(repo, sha)
    assert 'outside-value' not in seen['text']


def npm_tip(repo):
    (repo / 'package.json').write_text('{"name":"fixture"}\n')
    (repo / 'package-lock.json').write_text('{"lock":"committed"}\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'npm tip')
    return git(repo, 'rev-parse', 'HEAD')


def probe_raising(monkeypatch, failures):
    """Fake the HEAD probe: a URL in failures raises its exception, any other URL answers."""
    probed = []

    def urlopen(request, timeout):
        probed.append(request.full_url)
        assert request.get_method() == 'HEAD'
        for host, error in failures.items():
            if host in request.full_url:
                raise error
        return io.BytesIO()

    class Opener:
        def open(self, request, timeout):
            return urlopen(request, timeout)

    def build_opener(*handlers):
        assert handlers == (scan._NoRedirect,), 'the probe must not follow redirects'
        return Opener()

    monkeypatch.setattr(scan.urllib.request, 'build_opener', build_opener)
    return probed


def record_scans(monkeypatch, source_error=None, osv_error=None):
    calls = []

    def source(root):
        calls.append('semgrep')
        if source_error:
            raise source_error

    def dependencies(root):
        calls.append('osv')
        if osv_error:
            raise osv_error

    monkeypatch.setattr(scan, 'source', source)
    monkeypatch.setattr(scan, 'dependency_scan', dependencies)
    return calls


def tunnel_refused():
    # What urllib raises when a proxy answers CONNECT with 403, as in Claude's cloud sessions.
    return urllib.error.URLError(OSError('Tunnel connection failed: 403 Forbidden'))


def test_push_skips_only_the_scan_whose_server_is_unreachable(repo, monkeypatch, capsys):
    sha = npm_tip(repo)
    probe_raising(monkeypatch, {'semgrep.dev': tunnel_refused()})
    calls = record_scans(monkeypatch)
    scan.push_commit(repo, sha)
    assert calls == ['osv']
    err = capsys.readouterr().err
    assert 'semgrep (tip) skipped: https://semgrep.dev/ is unreachable' in err
    assert "CI's Security job runs it on the pull request" in err

    probe_raising(monkeypatch, {'api.osv.dev': tunnel_refused()})
    calls = record_scans(monkeypatch)
    scan.push_commit(repo, sha)
    assert calls == ['semgrep']
    assert 'osv-scanner (tip) skipped: https://api.osv.dev/ is unreachable' in capsys.readouterr().err


@pytest.mark.parametrize('error', [
    urllib.error.URLError(socket.gaierror(-2, 'Name or service not known')),
    urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused')),
    urllib.error.URLError(TimeoutError('timed out')),
    urllib.error.URLError(ssl.SSLError('handshake failed')),
    urllib.error.URLError(OSError(errno.ENETUNREACH, 'Network is unreachable')),
    urllib.error.URLError(OSError(errno.EHOSTUNREACH, 'No route to host')),
    ConnectionResetError(104, 'Connection reset by peer'),
    TimeoutError('read timed out'),
    tunnel_refused(),
])
def test_every_no_connection_probe_failure_skips_the_scan(repo, monkeypatch, error):
    probe_raising(monkeypatch, {'semgrep.dev': error})
    calls = record_scans(monkeypatch)
    scan.push_commit(repo, git(repo, 'rev-parse', 'HEAD'))
    assert calls == []


@pytest.mark.parametrize('error', [
    urllib.error.URLError(OSError('unexpected local failure')),
    PermissionError(13, 'Permission denied'),
    http.client.BadStatusLine('garbage'),
])
def test_other_probe_failures_fail_the_push_without_scanning(repo, monkeypatch, error):
    probe_raising(monkeypatch, {'semgrep.dev': error})
    calls = record_scans(monkeypatch)
    with pytest.raises(ValueError, match='could not probe https://semgrep.dev/'):
        scan.push_commit(repo, git(repo, 'rev-parse', 'HEAD'))
    assert calls == []


@pytest.mark.parametrize('answer', [
    urllib.error.HTTPError('https://semgrep.dev/', 405, 'Method Not Allowed', {}, None),
    urllib.error.HTTPError('https://semgrep.dev/', 301, 'Moved Permanently', {}, None),
    # The scanner judges the certificate with its own trust store.
    urllib.error.URLError(ssl.SSLCertVerificationError('certificate verify failed')),
])
def test_an_answer_or_unverified_certificate_runs_the_scan(repo, monkeypatch, capsys, answer):
    sha = npm_tip(repo)
    probe_raising(monkeypatch, {'semgrep.dev': answer, 'api.osv.dev': answer})
    calls = record_scans(monkeypatch)
    scan.push_commit(repo, sha)
    assert calls == ['semgrep', 'osv']
    assert 'skipped' not in capsys.readouterr().err


def test_no_redirect_handler_reports_a_redirect_as_an_answer():
    assert scan._NoRedirect().redirect_request(None, None, 301, 'Moved', {}, 'https://elsewhere.invalid/') is None


def test_a_skipped_scan_does_not_excuse_the_other_scans_failure(repo, monkeypatch):
    sha = npm_tip(repo)
    probe_raising(monkeypatch, {'semgrep.dev': tunnel_refused()})
    record_scans(monkeypatch, osv_error=subprocess.CalledProcessError(1, 'osv-scanner'))
    with pytest.raises(subprocess.CalledProcessError):
        scan.push_commit(repo, sha)
    probe_raising(monkeypatch, {'api.osv.dev': tunnel_refused()})
    record_scans(monkeypatch, source_error=subprocess.CalledProcessError(1, 'semgrep'))
    with pytest.raises(subprocess.CalledProcessError):
        scan.push_commit(repo, sha)


def test_ci_never_probes_or_skips(repo, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['security-scan.py', 'ci', '--root', str(repo)])
    monkeypatch.setattr(scan, 'unreachable', lambda url, name: pytest.fail('CI must not skip a scan'))
    calls = []
    monkeypatch.setattr(scan, 'structural', lambda root: calls.append('workflow'))
    monkeypatch.setattr(scan, 'source', lambda root: calls.append('source'))
    monkeypatch.setattr(scan, 'dependency_scan', lambda root: calls.append('dependencies'))
    assert scan.main() == 0
    assert calls == ['workflow', 'source', 'dependencies']


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


def test_mise_lock_records_no_slsa_provenance_for_osv_scanner():
    lock = tomllib.loads((ROOT / 'mise.lock').read_text())
    offenders = sorted(
        key
        for entry in lock['tools']['osv-scanner']
        for key, value in entry.items()
        if key.startswith('platforms.') and isinstance(value.get('provenance'), dict)
        and 'slsa' in value['provenance']
    )
    assert offenders == [], (
        'mise refuses (seen with 2026.9.16 and 2026.10.14) to install osv-scanner from a lock that records SLSA '
        'provenance while the Aqua registry entry names no signer. Delete the provenance.slsa '
        f'subtables under tools.osv-scanner after `mise lock` (found: {offenders}). On a version '
        'bump, recheck whether the registry now names a signer and, if it does, keep the subtables and remove this test.'
    )
