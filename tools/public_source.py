#!/usr/bin/env python3
"""Audit publishable source, or export a clean HEAD without private Git history."""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from privacy_scan import markers, scan_bytes

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'.git', '.claude', '.codex', '.agents', '.cursor', '.paseo',
                 '.idea', '.vscode', '.venv', '__pycache__', '.pytest_cache',
                 'internal', 'local', 'build', 'target', 'dist', 'corpora', 'data'}
PRIVATE_NAMES = {'agents.md', 'claude.md', 'gemini.md', 'memory.md', '.cursorrules',
                 'paseo.json', 'copilot-instructions.md', '.env'}
PRIVATE_SUFFIXES = {'.hspm', '.npz', '.pem', '.key', '.p12', '.pfx', '.keystore',
                    '.mobileprovision', '.pyc', '.log'}
PRIVATE_DOCS = ('docs/spacing-evaluation/*', 'docs/*RESEARCH*.md',
                'docs/research-*.md', 'docs/SPACING_EVALUATION*.md',
                'docs/SPACING_PAIRED_STATISTICS.md', 'docs/release/NIKL_APPROVAL_REQUEST.md',
                '.github/instructions/*', '.github/agents/*', '.github/prompts/*')
# Match personal absolute paths, but permit installer expressions such as /Users/$user.
PERSONAL_PATH = re.compile(rb'(?:/Users/|/home/)[A-Za-z0-9_.-]+/|[A-Za-z]:[\\/]+Users[\\/]+(?!public\b)[A-Za-z0-9_.-]+[\\/]', re.I)
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-proj-[A-Za-z0-9_-]{30,})')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def policy(root):
    data = json.loads((root / 'tools/public-source.json').read_text(encoding='utf-8'))
    if data.get('schema') != 1:
        raise ValueError('unsupported public-source policy')
    return data


def path_error(name, rules):
    p = PurePosixPath(name)
    parts = {v.lower() for v in p.parts}
    if p.is_absolute() or '..' in p.parts:
        return 'unsafe path'
    if parts & PRIVATE_PARTS or any(part.startswith('.claude') for part in parts) or p.name.lower() in PRIVATE_NAMES or any(fnmatch.fnmatchcase(p.name.lower(), pat) for pat in ('agents*.md', 'claude*.md')):
        return 'private development file'
    if p.suffix.lower() in PRIVATE_SUFFIXES or (p.name.startswith('.env.') and p.name != '.env.example'):
        return 'local data or credential file'
    if any(fnmatch.fnmatchcase(name.lower(), pat.lower()) for pat in PRIVATE_DOCS):
        return 'private report or instruction'
    if name not in rules['files'] and p.parts[0] not in rules['directories']:
        return 'path requires public-source review'
    return None


def content_error(data, marks):
    if scan_bytes(data, marks):
        return 'personal marker'
    # UTF-16 credentials/paths are checked as well as UTF-8 source.
    normalized = data.replace(b'\0', b'')
    if PERSONAL_PATH.search(normalized):
        return 'personal absolute path'
    if SECRET.search(normalized):
        return 'credential or private key'
    return None


def worktree_entries(root):
    names = git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
    modes = {}
    for entry in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not entry:
            continue
        meta, name = entry.split(b'\t', 1)
        mode, oid, stage = meta.split()
        if stage != b'0':
            raise ValueError('resolve merge conflicts before auditing')
        modes[os.fsdecode(name)] = mode.decode()
    entries = []
    for name in sorted(set(os.fsdecode(n) for n in names.split(b'\0') if n)):
        p = root / name
        # Staged deletions are absent from ls-files; unstaged deletions cannot export.
        if p.is_symlink():
            entries.append((name, b'', '120000'))
        elif p.is_file():
            mode = modes.get(name, '100755' if os.name != 'nt' and os.access(p, os.X_OK) else '100644')
            entries.append((name, p.read_bytes(), mode))
        elif p.exists():
            entries.append((name, b'', '160000'))
        else:
            raise ValueError(f'missing tracked file: {name}')
    return entries


def head_entries(root):
    entries = []
    for entry in git(root, 'ls-tree', '-rz', 'HEAD').split(b'\0'):
        if not entry:
            continue
        meta, name = entry.split(b'\t', 1)
        mode, kind, oid = meta.split()
        data = git(root, 'cat-file', 'blob', oid.decode()) if kind == b'blob' else b''
        entries.append((os.fsdecode(name), data, mode.decode()))
    return entries


def audit(entries, rules, marks):
    failures = []
    for name, data, mode in entries:
        reason = path_error(name, rules)
        if not reason and mode not in ('100644', '100755'):
            reason = 'symlink or submodule is not publishable'
        if not reason:
            reason = content_error(data, marks)
        if reason:
            failures.append((name, reason))
    return failures


def export(root, output, entries):
    if output.exists() or output.is_symlink():
        raise ValueError('export destination must not exist')
    # Never put an export inside the actual source folders or outside through a symlink.
    resolved = output.resolve()
    if root == resolved or root.is_relative_to(resolved):
        raise ValueError('export destination overlaps source checkout')
    if resolved.is_relative_to(root) and not resolved.is_relative_to(root / 'build'):
        raise ValueError('in-checkout exports must be under build/')
    output.mkdir(parents=True)
    for name, data, mode in entries:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode == '100755' else 0o644)
    print(f'Exported {len(entries)} files; no Git history or remote configuration copied.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['audit', 'export'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = ROOT
    if args.command == 'export':
        if not args.output:
            parser.error('export requires --output')
        if git(root, 'status', '--porcelain', '--untracked-files=all').strip():
            raise ValueError('export requires a clean committed worktree and index')
        entries = head_entries(root)
    else:
        entries = worktree_entries(root)
    failures = audit(entries, policy(root), markers())
    if failures:
        for name, reason in failures:
            print(f'{name}: {reason}', file=sys.stderr)
        print(f'Public-source audit FAILED: {len(failures)}/{len(entries)} files.', file=sys.stderr)
        return 1
    digest = hashlib.sha256()
    for name, data, mode in sorted(entries):
        digest.update(name.encode('utf-8') + b'\0' + mode.encode() + b'\0' + hashlib.sha256(data).digest())
    print(f'Public-source audit passed: {len(entries)} files; manifest SHA-256 {digest.hexdigest()}')
    if args.command == 'export':
        export(root, args.output, entries)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
