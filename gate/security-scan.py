#!/usr/bin/env python3
"""Pinned scanners shared by trusted Git hooks, Cursor and pull-request CI."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


VERSIONS = {"semgrep": "1.182.1", "zizmor": "1.31.1"}
OSV_VERSION = "2.7.0"

def dependencies(scanner, root):
    # Repository ignore files cannot suppress dependency findings.
    with tempfile.TemporaryDirectory(prefix="jsolly-osv-") as directory:
        config = Path(directory) / "empty.toml"
        config.write_text("")
        run([scanner, "scan", "source", "--lockfile", "package-lock.json",
             "--config", str(config), "--all-vulns"], root)


def binary(name, specification):
    """Resolve setup-installed tools for noninteractive Git clients too."""
    found = shutil.which(name)
    if found:
        return found
    candidate = Path(subprocess.check_output(
        ["mise", "which", "--tool", specification, name], cwd="/", text=True,
    ).strip())
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    raise ValueError(f"Missing {name}; run reviewed repository setup")


def run(args, root, **kwargs):
    print("security: " + " ".join(map(str, args)), file=sys.stderr)
    subprocess.run(args, cwd=root, check=True, stdout=sys.stderr, **kwargs)


def python_tool(name, args, root):
    run([binary("uvx", "uv@0.12.22"), "--from", f"{name}=={VERSIONS[name]}", name, *args], root)


def structural(root):
    python_tool("zizmor", ["--offline", ".github/workflows"], root)


def source(root):
    python_tool("semgrep", ["scan", "--config", "p/default", "--error",
                           "--metrics", "off", "--disable-version-check", "--no-git-ignore",
                           # Semgrep's built-in ignore list skips tests/ and build/; scan them.
                           "--x-ignore-semgrepignore-files",
                           "--exclude", "node_modules", "."], root)


def dependency_scan(root):
    scanner = binary("osv-scanner", f"osv-scanner@{OSV_VERSION}")
    version = subprocess.check_output([scanner, "--version"], text=True)
    if not re.search(rf"\b{re.escape(OSV_VERSION)}\b", version):
        raise ValueError(f"Install osv-scanner {OSV_VERSION} with repository setup")
    dependencies(scanner, root)


def secrets(root, *args):
    # Gitleaks 8.24.2 always loads source/.gitleaksignore, even with -i.
    if (root / ".gitleaksignore").exists() or (root / ".gitleaksignore").is_symlink():
        raise ValueError("Repository .gitleaksignore is unsupported by required secret checks")
    scanner = binary("gitleaks", "gitleaks@8.24.2")
    version = subprocess.check_output([scanner, "version"], text=True)
    if version.strip().removeprefix("v") != "8.24.2":
        raise ValueError("Install repository-pinned gitleaks 8.24.2")
    with tempfile.TemporaryDirectory(prefix="jsolly-gitleaks-") as directory:
        config = Path(directory) / "default.toml"
        config.write_text("[extend]\nuseDefault = true\n")
        run([scanner, *args, "--redact", "--no-banner", "--no-color",
             "--config", str(config), "--gitleaks-ignore-path", "/dev/null",
             "--ignore-gitleaks-allow"], root)


def git(root, *args):
    return subprocess.check_output(["git", "--no-replace-objects", "-C", str(root), *args])


def working_tree(root, tree):
    """Copy tracked and unignored files without following links outside the repo."""
    paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for raw in set(paths.split(b"\0")) - {b""}:
        path = Path(raw.decode())
        original = root / path
        if path.is_absolute() or ".." in path.parts or original.is_symlink():
            raise ValueError("Unsafe path in security scan")
        if not original.exists():
            continue
        if not original.resolve().is_relative_to(root):
            raise ValueError("Security scan path escapes the repository")
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)


def index_tree(root, tree):
    """Read staged blobs independently of worktree contents and index flags."""
    entries = git(root, "ls-files", "--stage", "-z")
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw = entry.split(b"\t", 1)
        mode, blob, stage = metadata.split()
        if stage != b"0" or mode not in (b"100644", b"100755", b"120000"):
            raise ValueError("Unmerged index or unsupported staged file")
        path = Path(os.fsdecode(raw))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe index path")
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Symlink blob text is scanned as data, never followed.
        target.write_bytes(git(root, "cat-file", "blob", blob.decode()))


def cursor(root, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("command"), str):
        raise ValueError("Malformed Cursor shell-hook input")
    with tempfile.TemporaryDirectory(prefix="jsolly-cursor-scan-") as directory:
        tree = Path(directory)
        working_tree(root, tree)
        secrets(tree, "dir", str(tree))
    with tempfile.TemporaryDirectory(prefix="jsolly-cursor-index-") as directory:
        tree = Path(directory)
        index_tree(root, tree)
        secrets(tree, "dir", str(tree))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("commit", "ci", "cursor"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    try:
        if args.phase == "cursor":
            cursor(root, json.load(sys.stdin))
            print(json.dumps({"permission": "allow"}))
        elif args.phase == "commit":
            structural(root)
        else:
            with tempfile.TemporaryDirectory(prefix="jsolly-ci-scan-") as directory:
                tree = Path(directory)
                working_tree(root, tree)
                failures = []
                for check in (structural, source, dependency_scan):
                    try:
                        check(tree)
                    except (OSError, ValueError, subprocess.CalledProcessError) as error:
                        print(f"{check.__name__} failed: {error}", file=sys.stderr)
                        failures.append(check.__name__)
                if failures:
                    raise ValueError("Failed security checks: " + ", ".join(failures))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"security scan failed: {error}", file=sys.stderr)
        if args.phase == "cursor":
            print(json.dumps({"permission": "deny", "user_message": "Secrets scan failed. Inspect the scanner output before retrying."}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
