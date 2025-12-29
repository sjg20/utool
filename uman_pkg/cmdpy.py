# SPDX-License-Identifier: GPL-2.0+
# Copyright 2025 Canonical Ltd
# Written by Simon Glass <simon.glass@canonical.com>

"""Pytest command for running U-Boot tests

This module handles the 'pytest' subcommand which runs U-Boot's pytest
test framework.
"""

import os
import re
import socket

# pylint: disable=import-error
from u_boot_pylib import command
from u_boot_pylib import tout

from uman_pkg import settings
from uman_pkg.util import exec_cmd, get_uboot_dir


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

    # Build PATH with hooks directories
    path_parts = []

    # Local hooks from U-Boot tree take precedence
    uboot_dir = get_uboot_dir()
    if uboot_dir:
        local_hooks = os.path.join(uboot_dir, 'test/hooks/bin')
        if os.path.exists(local_hooks):
            path_parts.append(local_hooks)

    # Then configured hooks from settings
    hooks = settings.get('test_hooks')
    if hooks and os.path.exists(hooks):
        hooks_bin = os.path.join(hooks, 'bin')
        if os.path.exists(hooks_bin):
            hooks = hooks_bin
        path_parts.append(hooks)

    if path_parts:
        current_path = os.environ.get('PATH', '')
        env['PATH'] = ':'.join(path_parts) + ':' + current_path

    return env


def list_qemu_boards():
    """List available QEMU boards using buildman

    Returns:
        list: Sorted list of QEMU board names
    """
    uboot_dir = get_uboot_dir()
    orig_dir = os.getcwd()
    try:
        if uboot_dir:
            os.chdir(uboot_dir)
        result = command.run_pipe([['buildman', '-nv', 'qemu']], capture=True,
                                   capture_stderr=True, raise_on_error=False)
    finally:
        os.chdir(orig_dir)

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


def parse_hook_config(config_path):
    """Parse shell variable assignments from a hook config file

    Args:
        config_path (str): Path to the config file

    Returns:
        dict: Dictionary of variable names to values
    """
    variables = {}
    if not os.path.exists(config_path):
        return variables

    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Match variable assignments: name=value or name="value"
            match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$', line)
            if match:
                name, value = match.groups()
                # Remove surrounding quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                variables[name] = value
    return variables


def expand_vars(value, env):
    """Expand shell-style variable references in a string

    Args:
        value (str): String potentially containing ${VAR} references
        env (dict): Environment variables for substitution

    Returns:
        str: String with variables expanded
    """
    def replace_var(match):
        var_name = match.group(1)
        return env.get(var_name, f'${{{var_name}}}')

    return re.sub(r'\$\{([^}]+)\}', replace_var, value)


def get_board_config(board):
    """Get the hook configuration for a board

    Args:
        board (str): Board name

    Returns:
        dict: Configuration with keys like 'console_impl', 'qemu_binary',
            'qemu_machine', 'qemu_extra_args', 'qemu_kernel_args', etc.,
            or None if not found
    """
    hooks = settings.get('test_hooks')
    if not hooks:
        tout.error('test_hooks not configured in settings')
        return None

    hooks_bin = os.path.join(hooks, 'bin')
    if not os.path.exists(hooks_bin):
        tout.error(f'Hooks bin directory not found: {hooks_bin}')
        return None

    hostname = socket.gethostname()
    board_id = 'na'  # Default board identifier

    # Build config file path
    cfg = os.path.join(hooks_bin, hostname, f'conf.{board}_{board_id}')

    # Resolve symlinks
    if os.path.islink(cfg):
        cfg = os.path.realpath(cfg)

    if not os.path.exists(cfg):
        tout.error(f'Config file not found: {cfg}')
        return None

    return parse_hook_config(cfg)


def get_qemu_command(board, args):
    """Build the QEMU command line from hook-config files

    Args:
        board (str): Board name
        args (argparse.Namespace): Arguments from cmdline

    Returns:
        str: QEMU command line, or None if not a QEMU board
    """
    config = get_board_config(board)
    if not config:
        return None

    # Check if this is a QEMU board
    if config.get('console_impl') != 'qemu':
        tout.warning(f'Board {board} is not a QEMU board '
                     f'(console_impl={config.get("console_impl")})')
        return None

    # Build environment for variable expansion
    if args.build_dir:
        build_dir = args.build_dir
    else:
        base_dir = settings.get('build_dir', '/tmp/b')
        build_dir = f'{base_dir}/{board}'

    env = os.environ.copy()
    env['U_BOOT_BUILD_DIR'] = build_dir
    env['UBOOT_TRAVIS_BUILD_DIR'] = build_dir

    # Add OPENSBI if configured
    pytest_vars = pytest_env(board)
    env.update(pytest_vars)

    # Extract QEMU command components
    qemu_binary = config.get('qemu_binary', 'qemu-system-unknown')
    qemu_machine = config.get('qemu_machine', '')
    qemu_extra_args = config.get('qemu_extra_args', '')
    qemu_kernel_args = config.get('qemu_kernel_args', '')

    # Expand variables
    qemu_extra_args = expand_vars(qemu_extra_args, env)
    qemu_kernel_args = expand_vars(qemu_kernel_args, env)

    # Build command line
    cmd_parts = [qemu_binary]
    if qemu_extra_args:
        cmd_parts.append(qemu_extra_args)
    cmd_parts.append(f'-M {qemu_machine}')
    if qemu_kernel_args:
        cmd_parts.append(qemu_kernel_args)

    return ' '.join(cmd_parts)


def do_pytest(args):  # pylint: disable=too-many-return-statements,too-many-branches
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

    # Handle --show-cmd option
    if args.show_cmd:
        qemu_cmd = get_qemu_command(board, args)
        if qemu_cmd:
            print(qemu_cmd)
            return 0
        return 1

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

    pytest_vars = pytest_env(args.board)
    cmd = build_pytest_cmd(args)

    env = os.environ.copy()
    env.update(pytest_vars)
    result = exec_cmd(cmd, args.dry_run, env=env, capture=False)

    if result is None:  # dry-run
        return 0

    if result.return_code != 0:
        if not args.quiet:
            tout.error('pytest failed')
        return result.return_code

    if not args.quiet:
        tout.notice('pytest passed')
    return 0
