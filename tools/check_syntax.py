#!/usr/bin/env python3
"""Offline syntax checks. Does not execute router programs or contact devices."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def check(bundle):
    from lupa.lua51 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    compile_only = lua.eval('function(code,name) local f,e=loadstring(code,name); return f~=nil,e end')
    bash = os.environ.get('BASH_BINARY') or shutil.which('bash')
    if os.name == 'nt' and not os.environ.get('BASH_BINARY'):
        p = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe'
        if p.is_file():
            bash = str(p)
    if not bash:
        raise RuntimeError('Bash is required for shell syntax checking')
    counts = {'lua': 0, 'shell': 0, 'json': 0, 'javascript': 0, 'nft_structure_only': 0}
    for p in sorted(Path(bundle).rglob('*')):
        if not p.is_file():
            continue
        text = p.read_text(encoding='utf-8')
        if text.startswith('#!/usr/bin/lua') or p.suffix == '.lua':
            if text.startswith('#!'):
                text = text.split('\n', 1)[1]
            ok, err = compile_only(text, '@' + p.name)
            if not ok:
                raise RuntimeError(str(err))
            counts['lua'] += 1
        elif text.startswith('#!/bin/sh') or p.suffix == '.sh':
            subprocess.run([bash, '-n', str(p.resolve())], check=True, capture_output=True, text=True)
            counts['shell'] += 1
        elif p.suffix == '.json':
            json.loads(text)
            counts['json'] += 1
        elif p.suffix == '.js':
            subprocess.run(['node', '--check', str(p)], check=True, capture_output=True, text=True)
            counts['javascript'] += 1
        elif p.suffix == '.nft':
            if text.count('{') != text.count('}') or '@HOME_' in text or '@CLIENT_' in text:
                raise RuntimeError('Unbalanced/unrendered nft template: ' + p.name)
            counts['nft_structure_only'] += 1
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.bundle), sort_keys=True))
        print('PASS: compile-only Lua/shell/JS/JSON. nft: structure only, NOT Linux nft/fw4 compilation.')
    except (ImportError, OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, 'FAIL: %s\n' % exc)
