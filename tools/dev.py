#!/usr/bin/env python3
"""Common development commands: python tools/dev.py doctor|check|core|engine|tools."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'engine') + os.pathsep + env.get('PYTHONPATH', '')
    print('+ ' + ' '.join(str(a) for a in args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['doctor', 'check', 'core', 'engine', 'tools'])
    args = parser.parse_args()
    if args.command == 'doctor':
        print(f'{platform.system()} {platform.machine()} / Python {platform.python_version()}')
        for tool in ('git', 'cargo', 'rustc'):
            print(f'{tool}: {shutil.which(tool) or "MISSING"}')
        run('git', 'status', '--short', '--branch')
        run(sys.executable, 'tools/versions.py', 'check')
        return
    if args.command == 'check':
        run(sys.executable, 'tools/versions.py', 'check')
        run(sys.executable, 'tools/public_source.py', 'audit')
    if args.command in ('check', 'core'):
        run('cargo', 'test', '--manifest-path', 'core/Cargo.toml', '--offline', '--locked')
    if args.command in ('check', 'tools'):
        run(sys.executable, '-m', 'unittest', 'discover', '-s', 'tools/tests', '-p', 'test_*.py')
    if args.command in ('check', 'engine'):
        run(sys.executable, '-m', 'pytest', 'engine/tests', '-q')


if __name__ == '__main__':
    try:
        main()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
