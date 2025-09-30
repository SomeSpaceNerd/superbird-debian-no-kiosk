#!/usr/bin/env python3
"""
Show a tree of device values starting from current directory
    meant to be used in /sys/
"""
# pylint: disable=broad-exception-caught,invalid-name

from pathlib import Path

pathlist = Path().cwd().rglob('**/*')

cur_dir = None
for path in pathlist:
    path_str = str(path).removeprefix(str(Path().cwd()) + '/')
    if path.parent != cur_dir:
        cur_dir = path.parent
        print('-' * 80)
        print('')
        print(str(cur_dir))
        print('-' * 80)
    if path.is_file():
        try:
            with open(path, 'r', encoding='utf-8') as ff:
                path_value = ff.read().strip()
        except Exception:
            path_value = ''
        path_value = ','.join(path_value.splitlines())

        print(f'{path_str}: {path_value}')
    if path.is_symlink():
        target = path.readlink()
        print(f'{path_str} -> {target}')
