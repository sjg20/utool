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


def setup_riscv_env(board, env):
    """Set up OPENSBI environment for RISC-V boards

    Args:
        board (str): Board name
        env (dict): Environment variables dict to update
    """
    # Select 32-bit or 64-bit OpenSBI based on board name
    if 'riscv32' in board:
        opensbi = settings.get('opensbi_rv32', fallback=None)
        # Fallback: derive rv32 path from rv64 path
        if not opensbi:
            rv64_path = settings.get('opensbi', fallback=None)
            if rv64_path:
                opensbi = rv64_path.replace('.bin', '_rv32.bin')
    else:
        opensbi = settings.get('opensbi', fallback=None)
    if opensbi and os.path.exists(opensbi):
        env['OPENSBI'] = opensbi
    elif opensbi:
        tout.warning(f'OPENSBI firmware not found: {opensbi}')
    else:
        tout.warning(f'No OPENSBI firmware configured for {board}')


def setup_sbsa_env(board, env):
    """Set up TF-A environment for SBSA boards

    Args:
        board (str): Board name
        env (dict): Environment variables dict to update
    """
    tfa_dir = settings.get('tfa_dir', fallback=None)
    # Fallback: derive tfa_dir from blobs_dir
    if not tfa_dir:
        blobs_dir = settings.get('blobs_dir', fallback=None)
        if blobs_dir:
            tfa_dir = os.path.join(blobs_dir, 'tfa')
    if tfa_dir and os.path.exists(tfa_dir):
        # Add TF-A directory to binman search path
        current = os.environ.get('BINMAN_INDIRS', '')
        if current:
            env['BINMAN_INDIRS'] = f'{current}:{tfa_dir}'
        else:
            env['BINMAN_INDIRS'] = tfa_dir
    elif tfa_dir:
        tout.warning(f'TF-A directory not found: {tfa_dir}')
    else:
        tout.warning(f'No TF-A directory configured for {board}')


def pytest_env(board):
    """Set up environment variables for pytest testing

    Args:
        board (str): Board name

    Returns:
        dict: Environment variables that were set (not the full environment)
    """
    env = {}

    if 'riscv' in board:
        setup_riscv_env(board, env)

    if 'sbsa' in board:
        setup_sbsa_env(board, env)

    hooks = settings.get('test_hooks')
    if hooks and os.path.exists(hooks):
        current_path = os.environ.get('PATH', '')
        if hooks not in current_path:
            env['PATH'] = f"{current_path}:{hooks}"

    return env


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


def get_uboot_dir():
    """Get the U-Boot source directory

    Checks if current directory is a U-Boot tree, otherwise uses $USRC.

    Returns:
        str: Path to U-Boot source directory, or None if not found
    """
    # Check if current directory is a U-Boot tree
    if os.path.exists('./test/py/test.py'):
        return os.getcwd()

    # Try USRC environment variable
    usrc = os.environ.get('USRC')
    if usrc and os.path.exists(os.path.join(usrc, 'test/py/test.py')):
        return usrc

    return None


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

    # Find U-Boot source directory
    uboot_dir = get_uboot_dir()
    if not uboot_dir:
        tout.error('Not in a U-Boot tree and $USRC not set')
        return 1

    # Change to U-Boot directory if needed
    if uboot_dir != os.getcwd():
        tout.info(f'Changing to U-Boot directory: {uboot_dir}')
        os.chdir(uboot_dir)

    tout.info(f'Running pytest for board: {args.board}')

    env = pytest_env(args.board)
    cmd = build_pytest_cmd(args)

    env = os.environ.copy()
    env.update(env)
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
