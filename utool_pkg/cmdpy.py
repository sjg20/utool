# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Pytest command for running U-Boot tests

This module handles the 'pytest' subcommand which runs U-Boot's pytest
test framework.
"""

import os

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from utool_pkg import settings
from utool_pkg.util import exec_cmd


def pytest_env(board):
    """Set up environment variables for pytest testing

    Args:
        board (str): Board name

    Returns:
        dict: Environment variables that were set (not the full environment)
    """
    env_vars = {}

    if 'riscv' in board:
        opensbi = settings.get('opensbi')
        if opensbi and os.path.exists(opensbi):
            env_vars['OPENSBI'] = opensbi
        else:
            tout.warning('No OPENSBI firmware found for RISC-V')

    hooks = settings.get('test_hooks')
    if hooks and os.path.exists(hooks):
        current_path = os.environ.get('PATH', '')
        if hooks not in current_path:
            env_vars['PATH'] = f"{current_path}:{hooks}"

    return env_vars


def list_qemu_boards():
    """List available QEMU boards using buildman

    Returns:
        list: Sorted list of QEMU board names
    """
    result = command.run_pipe([['buildman', '-nv', 'qemu']], capture=True,
                               capture_stderr=True, raise_on_error=False)
    if result.return_code != 0:
        return []

    boards = []
    for line in result.stdout.splitlines():
        # Board names are on indented lines after "qemu : N boards"
        if line.startswith('   '):
            boards.extend(line.split())
    return sorted(boards)


def build_pytest_cmd(args):
    """Build the pytest command line

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        list: Command and arguments to run
    """
    cmd = ['./test/py/test.py']
    cmd.extend(['-B', args.board])

    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{args.board}'
    cmd.extend(['--build-dir', build_dir])

    if not args.no_build:
        cmd.append('--build')

    cmd.append('--buildman')

    cmd.extend(['--id', 'na'])

    if args.test_spec:
        cmd.extend(['-k', ' '.join(args.test_spec)])

    if args.timeout != 300:
        cmd.extend(['-o', f'faulthandler_timeout={args.timeout}'])

    cmd.append('-q')
    if args.quiet:
        cmd.extend(['--no-header', '--quiet-hooks'])
    if args.show_output:
        cmd.append('-s')
    if args.timing is not None:
        cmd.extend(['--timing', '--durations=0',
                    f'--durations-min={args.timing}'])

    return cmd


def do_pytest(args):
    """Handle pytest command - run pytest tests for U-Boot

    Args:
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        int: Exit code
    """
    if args.list_boards:
        boards = list_qemu_boards()
        if boards:
            tout.notice('Available QEMU boards:')
            for board in boards:
                print(f'  {board}')
        else:
            tout.warning('No QEMU boards found (is buildman configured?)')
        return 0

    board = args.board or os.environ.get('b')
    if not board:
        tout.error('Board is required: use -b BOARD or set $b (use -l to list)')
        return 1
    args.board = board

    tout.info(f'Running pytest for board: {args.board}')

    env_vars = pytest_env(args.board)
    cmd = build_pytest_cmd(args)

    env = os.environ.copy()
    env.update(env_vars)
    result = exec_cmd(cmd, args, env=env, capture=False)

    if result is None:  # dry-run
        return 0

    if result.return_code != 0:
        if not args.quiet:
            tout.error('pytest failed')
        return result.return_code

    if not args.quiet:
        tout.notice('pytest passed')
    return 0
